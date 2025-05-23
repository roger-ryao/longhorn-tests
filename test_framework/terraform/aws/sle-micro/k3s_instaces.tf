# Create controlplane instances for k3s
resource "aws_instance" "lh_aws_instance_controlplane_k3s" {
 depends_on = [
    aws_subnet.lh_aws_public_subnet,
  ]

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  availability_zone = var.aws_availability_zone

  ami           = data.aws_ami.aws_ami_sles.id
  instance_type = var.lh_aws_instance_type_controlplane

  subnet_id = aws_subnet.lh_aws_public_subnet.id
  vpc_security_group_ids = [
    aws_security_group.lh_aws_secgrp_public.id
  ]

  root_block_device {
    delete_on_termination = true
    volume_size = var.block_device_size_controlplane
  }

  key_name = aws_key_pair.lh_aws_pair_key.key_name

  tags = {
    Name = "${var.lh_aws_instance_name_controlplane}-${count.index}-${random_string.random_suffix.id}"
    DoNotDelete = "true"
    Owner = "longhorn-infra"
  }
}

# Create worker instances for k3s
resource "aws_instance" "lh_aws_instance_worker_k3s" {
  depends_on = [
    aws_internet_gateway.lh_aws_igw,
    aws_subnet.lh_aws_private_subnet,
    aws_instance.lh_aws_instance_controlplane_k3s
  ]

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  availability_zone = var.aws_availability_zone

  ami           = data.aws_ami.aws_ami_sles.id
  instance_type = var.lh_aws_instance_type_worker
  associate_public_ip_address = true

  subnet_id = aws_subnet.lh_aws_public_subnet.id
  vpc_security_group_ids = [
    aws_security_group.lh_aws_secgrp_public.id
  ]

  root_block_device {
    delete_on_termination = true
    volume_size = var.block_device_size_worker
  } 

  key_name = aws_key_pair.lh_aws_pair_key.key_name

  tags = {
    Name = "${var.lh_aws_instance_name_worker}-${count.index}-${random_string.random_suffix.id}"
    DoNotDelete = "true"
    Owner = "longhorn-infra"
  }
}

resource "aws_volume_attachment" "lh_aws_hdd_volume_att_k3s" {

  count = var.use_hdd && var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  device_name  = "/dev/xvdh"
  volume_id    = aws_ebs_volume.lh_aws_hdd_volume[count.index].id
  instance_id  = aws_instance.lh_aws_instance_worker_k3s[count.index].id
  force_detach = true
}

resource "aws_volume_attachment" "lh_aws_ssd_volume_att_k3s" {

  count = var.extra_block_device && var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  device_name  = "/dev/xvdh"
  volume_id    = aws_ebs_volume.lh_aws_ssd_volume[count.index].id
  instance_id  = aws_instance.lh_aws_instance_worker_k3s[count.index].id
  force_detach = true
}

resource "aws_lb_target_group_attachment" "lh_aws_lb_tg_443_attachment_k3s" {

  depends_on = [
    aws_lb_target_group.lh_aws_lb_tg_443,
    aws_instance.lh_aws_instance_worker_k3s
  ]

  count            = var.create_load_balancer ? length(aws_instance.lh_aws_instance_worker_k3s) : 0
  target_group_arn = aws_lb_target_group.lh_aws_lb_tg_443[0].arn
  target_id        = aws_instance.lh_aws_instance_worker_k3s[count.index].id
}

# Associate every EIP with controlplane instance
resource "aws_eip_association" "lh_aws_eip_assoc_k3s" {
  depends_on = [
    aws_instance.lh_aws_instance_controlplane_k3s,
    aws_eip.lh_aws_eip_controlplane
  ]

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  instance_id   = element(aws_instance.lh_aws_instance_controlplane_k3s, count.index).id
  allocation_id = element(aws_eip.lh_aws_eip_controlplane, count.index).id
}

# node initialization step 1: register the system to get repos
resource "null_resource" "registration_controlplane_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  depends_on = [
    aws_instance.lh_aws_instance_controlplane_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "sudo transactional-update register -r ${var.registration_code}",
    ]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_eip.lh_aws_eip_controlplane[0].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

# node initialization step 1: register the system to get repos
resource "null_resource" "registration_worker_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  depends_on = [
    aws_instance.lh_aws_instance_worker_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "sudo transactional-update register -r ${var.registration_code}",
    ]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_instance.lh_aws_instance_worker_k3s[count.index].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }
}

# node initialization step 2: install required packages after get repos
resource "null_resource" "package_install_controlplane_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  depends_on = [
    null_resource.registration_controlplane_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "sudo transactional-update pkg install -y open-iscsi nfs-client jq",
      "sudo shutdown -r now",
    ]

    on_failure = continue

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_eip.lh_aws_eip_controlplane[0].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

resource "time_sleep" "wait_controlplane_1_minute_k3s" {

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  depends_on = [
    null_resource.package_install_controlplane_k3s
  ]

  create_duration = "60s"
}

resource "aws_ec2_instance_state" "controlplane_state_k3s" {

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  depends_on = [
    time_sleep.wait_controlplane_1_minute_k3s
  ]

  instance_id = aws_instance.lh_aws_instance_controlplane_k3s[count.index].id
  state       = "running"
}

# node initialization step 2: install required packages after get repos
resource "null_resource" "package_install_worker_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  depends_on = [
    null_resource.registration_worker_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "sudo transactional-update pkg install -y open-iscsi nfs-client cryptsetup device-mapper jq",
      "sudo shutdown -r now",
    ]

    on_failure = continue

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_instance.lh_aws_instance_worker_k3s[count.index].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

resource "time_sleep" "wait_worker_1_minute_k3s" {

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  depends_on = [
    null_resource.package_install_worker_k3s
  ]

  create_duration = "60s"
}

resource "aws_ec2_instance_state" "worker_state_k3s" {

  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  depends_on = [
    time_sleep.wait_worker_1_minute_k3s
  ]

  instance_id = aws_instance.lh_aws_instance_worker_k3s[count.index].id
  state       = "running"
}

# node initialization step 3: setup k3s cluster for master node
resource "null_resource" "cluster_setup_controlplane_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_controlplane : 0

  depends_on = [
    aws_ec2_instance_state.controlplane_state_k3s
  ]

  provisioner "remote-exec" {

    inline = [data.template_file.provision_k3s_server.rendered]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_eip.lh_aws_eip_controlplane[0].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

# node initialization step 3: setup k3s cluster for worker node
resource "null_resource" "cluster_setup_worker_k3s" {
  count = var.k8s_distro_name == "k3s" ? var.lh_aws_instance_count_worker : 0

  depends_on = [
    aws_ec2_instance_state.worker_state_k3s,
    null_resource.cluster_setup_controlplane_k3s
  ]

  provisioner "remote-exec" {

    inline = [data.template_file.provision_k3s_agent.rendered]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_instance.lh_aws_instance_worker_k3s[count.index].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

# node initialization step 4: make sure k8s components running
resource "null_resource" "make_sure_k8s_components_running_controlplane_k3s" {
  count = var.k8s_distro_name == "k3s" ? 1 : 0

  depends_on = [
    null_resource.cluster_setup_controlplane_k3s,
    null_resource.cluster_setup_worker_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "until (kubectl get pods -A | grep 'Running'); do echo 'Waiting for k3s startup'; sleep 5; done"
    ]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_eip.lh_aws_eip_controlplane[0].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

}

# node initialization step 5: download KUBECONFIG file for k3s
resource "null_resource" "rsync_kubeconfig_file" {
  count = var.k8s_distro_name == "k3s" ? 1 : 0

  depends_on = [
    aws_instance.lh_aws_instance_controlplane_k3s,
    aws_eip.lh_aws_eip_controlplane,
    aws_eip_association.lh_aws_eip_assoc_k3s,
    null_resource.make_sure_k8s_components_running_controlplane_k3s
  ]

  provisioner "remote-exec" {

    inline = [
      "until([ -f /etc/rancher/k3s/k3s.yaml ] && [ `kubectl get node -o jsonpath='{.items[*].status.conditions}'  | jq '.[] | select(.type  == \"Ready\").status' | grep -ci true` -eq $((${var.lh_aws_instance_count_controlplane} + ${var.lh_aws_instance_count_worker})) ]); do echo \"waiting for k3s cluster nodes to be running\"; sleep 2; done"
    ]

    connection {
      type     = "ssh"
      user     = "ec2-user"
      host     = aws_eip.lh_aws_eip_controlplane[0].public_ip
      private_key = file(var.aws_ssh_private_key_file_path)
    }
  }

  provisioner "local-exec" {
    command = "rsync -aPvz --rsync-path=\"sudo rsync\" -e \"ssh -o StrictHostKeyChecking=no -l ec2-user -i ${var.aws_ssh_private_key_file_path}\" ${aws_eip.lh_aws_eip_controlplane[0].public_ip}:/etc/rancher/k3s/k3s.yaml .  && sed -i 's#https://127.0.0.1:6443#https://${aws_eip.lh_aws_eip_controlplane[0].public_ip}:6443#' k3s.yaml"
  }
}
