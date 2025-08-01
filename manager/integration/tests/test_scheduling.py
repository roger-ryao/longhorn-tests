import common
import pytest
import time
import copy
import math

from common import apps_api  # NOQA
from common import client  # NOQA
from common import core_api  # NOQA
from common import make_deployment_with_pvc  # NOQA
from common import pod  # NOQA
from common import pvc  # NOQA
from common import settings_reset # NOQA
from common import statefulset  # NOQA
from common import storage_class  # NOQA
from common import sts_name  # NOQA
from common import volume_name  # NOQA

from common import get_longhorn_api_client
from common import get_self_host_id
from common import update_setting
from common import size_to_string

from common import cleanup_disks_on_node
from common import cleanup_node_disks
from common import create_host_disk
from common import get_update_disks
from common import set_node_scheduling
from common import update_node_disks
from common import wait_for_disk_status
from common import wait_for_disk_update
from common import wait_for_node_update

from common import check_volume_data
from common import cleanup_volume
from common import cleanup_volume_by_name
from common import create_and_check_volume
from common import delete_replica_on_test_node
from common import wait_for_volume_degraded
from common import wait_for_volume_detached
from common import wait_for_volume_healthy
from common import wait_for_volume_replica_rebuilt_on_same_node_different_disk
from common import wait_for_volume_replica_count
from common import write_volume_random_data

from common import create_and_wait_statefulset
from common import delete_and_wait_statefulset
from common import delete_statefulset
from common import get_statefulset_pod_info

from common import create_and_wait_pod
from common import delete_and_wait_pod
from common import wait_delete_pod
from common import wait_for_pods_volume_state
from common import write_pod_volume_random_data
from common import get_pod_data_md5sum

from common import create_pv_for_volume
from common import create_pvc_for_volume
from common import create_storage_class

from common import wait_scheduling_failure
from common import wait_for_rebuild_complete
from common import wait_for_rebuild_start
from common import wait_for_replica_running

from common import crash_engine_process_with_sigkill
from common import set_node_tags
from common import wait_for_node_tag_update
from common import wait_for_volume_condition_scheduled
from common import cleanup_host_disks
from common import wait_for_volume_delete

from common import Mi, Gi
from common import DATA_SIZE_IN_MB_2
from common import DEFAULT_DISK_PATH
from common import RETRY_COUNTS
from common import RETRY_INTERVAL
from common import RETRY_INTERVAL_LONG
from common import SETTING_DEFAULT_DATA_LOCALITY
from common import SETTING_REPLICA_AUTO_BALANCE
from common import SETTING_REPLICA_AUTO_BALANCE_DISK_PRESSURE_PERCENTAGE
from common import SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY
from common import VOLUME_FIELD_ROBUSTNESS
from common import VOLUME_ROBUSTNESS_HEALTHY
from common import VOLUME_FRONTEND_BLOCKDEV, SNAPSHOT_DATA_INTEGRITY_IGNORED
from common import VOLUME_ROBUSTNESS_DEGRADED, RETRY_COUNTS_SHORT
from common import SETTING_ALLOW_EMPTY_NODE_SELECTOR_VOLUME
from common import SIZE, CONDITION_STATUS_FALSE, CONDITION_STATUS_TRUE
from common import SETTING_REPLICA_ZONE_SOFT_ANTI_AFFINITY
from common import SETTING_REPLICA_DISK_SOFT_ANTI_AFFINITY
from common import SETTING_ALLOW_EMPTY_DISK_SELECTOR_VOLUME
from common import DATA_ENGINE

from time import sleep


@pytest.yield_fixture(autouse=True)
def reset_settings():
    yield
    client = get_longhorn_api_client()  # NOQA
    host_id = get_self_host_id()
    node = client.by_id_node(host_id)
    node = set_node_scheduling(client, node, allowScheduling=True)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="true")


def get_host_replica(volume, host_id):
    """
    Get the replica of the volume that is running on the test host. Trigger a
    failed assertion if it can't be found.
    :param volume: The volume to get the replica from.
    :param host_id: The ID of the test host.
    :return: The replica hosted on the test host.
    """
    host_replica = None
    for i in volume.replicas:
        if i.hostId == host_id:
            host_replica = i
    assert host_replica is not None
    return host_replica


# We check to make sure the replica is found, running, and in RW mode (not
# rebuilding) since the longhorn-engine has the latest status compared to
# longhorn-manager, which might be in an intermediate state.
def wait_new_replica_ready(client, volume_name, replica_names):  # NOQA
    """
    Wait for a new replica to be found on the specified volume. Trigger a
    failed assertion if one can't be found.
    :param client: The Longhorn client to use in the request.
    :param volume_name: The name of the volume.
    :param replica_names: The list of names of the volume's old replicas.
    """
    new_replica_ready = False
    wait_for_rebuild_complete(client, volume_name)
    for _ in range(RETRY_COUNTS):
        v = client.by_id_volume(volume_name)
        for r in v.replicas:
            if r["name"] not in replica_names and r["running"] and \
                    r["mode"] == "RW":
                new_replica_ready = True
                break
        if new_replica_ready:
            break
        sleep(RETRY_INTERVAL)
    assert new_replica_ready


@pytest.mark.v2_volume_test  # NOQA
def test_soft_anti_affinity_scheduling(client, volume_name):  # NOQA
    """
    Test that volumes with Soft Anti-Affinity work as expected.

    With Soft Anti-Affinity, a new replica should still be scheduled on a node
    with an existing replica, which will result in "Healthy" state but limited
    redundancy.

    1. Create a volume and attach to the current node
    2. Generate and write `data` to the volume.
    3. Set `soft anti-affinity` to true
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
    6. Wait for the volume to complete rebuild. Volume should have 3 replicas.
    7. Verify `data`
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="true")
    node = client.by_id_node(host_id)
    node = set_node_scheduling(client, node, allowScheduling=False)
    replica_names = list(map(lambda replica: replica.name, volume.replicas))
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    wait_new_replica_ready(client, volume_name, replica_names)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_soft_anti_affinity_detach(client, volume_name):  # NOQA
    """
    Test that volumes with Soft Anti-Affinity can detach and reattach to a
    node properly.

    1. Create a volume and attach to the current node.
    2. Generate and write `data` to the volume
    3. Set `soft anti-affinity` to true
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
    6. Wait for the new replica to be rebuilt
    7. Detach the volume.
    8. Verify there are 3 replicas
    9. Attach the volume again. Verify there are still 3 replicas
    10. Verify the `data`.
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="true")
    node = client.by_id_node(host_id)
    set_node_scheduling(client, node, allowScheduling=False)
    replica_names = list(map(lambda replica: replica.name, volume.replicas))
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    wait_new_replica_ready(client, volume_name, replica_names)
    volume = wait_for_volume_healthy(client, volume_name)
    volume.detach()
    volume = wait_for_volume_detached(client, volume_name)
    assert len(volume.replicas) == 3

    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_hard_anti_affinity_scheduling(client, volume_name):  # NOQA
    """
    Test that volumes with Hard Anti-Affinity work as expected.

    With Hard Anti-Affinity, scheduling on nodes with existing replicas should
    be forbidden, resulting in "Degraded" state.

    1. Create a volume and attach to the current node
    2. Generate and write `data` to the volume.
    3. Set `soft anti-affinity` to false
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
        1. Verify volume will be in degraded state.
        2. Verify volume reports condition `scheduled == false`
        3. Verify only two replicas of volume are healthy.
    6. Check volume `data`
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="false")
    node = client.by_id_node(host_id)
    set_node_scheduling(client, node, allowScheduling=False)
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    # Instead of waiting for timeout and lengthening the tests a significant
    # amount we can make sure the scheduling isn't working by making sure the
    # volume becomes Degraded and reports a scheduling error.
    wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)
    # While there are three replicas that should exist to meet the Volume's
    # request, only two of those volumes should actually be Healthy.
    volume = client.by_id_volume(volume_name)
    assert sum([1 for replica in volume.replicas if replica.running and
                replica.mode == "RW"]) == 2

    # Two replicas in total should exist.
    assert len(volume.replicas) == 2
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_hard_anti_affinity_detach(client, volume_name):  # NOQA
    """
    Test that volumes with Hard Anti-Affinity are still able to detach and
    reattach to a node properly, even in degraded state.

    1. Create a volume and attach to the current node
    2. Generate and write `data` to the volume.
    3. Set `soft anti-affinity` to false
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
        1. Verify volume will be in degraded state.
        2. Verify volume reports condition `scheduled == false`
    6. Detach the volume.
    7. Verify that volume only have 2 replicas
        1. Unhealthy replica will be removed upon detach.
    8. Attach the volume again.
        1. Verify volume will be in degraded state.
        2. Verify volume reports condition `scheduled == false`
        3. Verify only two replicas of volume are healthy.
    9. Check volume `data`
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="false")
    node = client.by_id_node(host_id)
    set_node_scheduling(client, node, allowScheduling=False)
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    volume = wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)
    volume.detach()
    volume = wait_for_volume_detached(client, volume_name)
    assert len(volume.replicas) == 2

    volume.attach(hostId=host_id)
    # Make sure we're still not getting another successful replica.
    volume = wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)
    assert sum([1 for replica in volume.replicas if replica.running and
                replica.mode == "RW"]) == 2
    assert len(volume.replicas) == 2
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_hard_anti_affinity_live_rebuild(client, volume_name):  # NOQA
    """
    Test that volumes with Hard Anti-Affinity can build new replicas live once
    a valid node is available.

    If no nodes without existing replicas are available, the volume should
    remain in "Degraded" state. However, once one is available, the replica
    should now be scheduled successfully, with the volume returning to
    "Healthy" state.

    1. Create a volume and attach to the current node
    2. Generate and write `data` to the volume.
    3. Set `soft anti-affinity` to false
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
        1. Verify volume will be in degraded state.
        2. Verify volume reports condition `scheduled == false`
    6. Enable the current node's scheduling
    7. Wait for volume to start rebuilding and become healthy again
    8. Check volume `data`
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="false")
    node = client.by_id_node(host_id)
    set_node_scheduling(client, node, allowScheduling=False)
    replica_names = map(lambda replica: replica.name, volume.replicas)
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)
    # Allow scheduling on host node again
    set_node_scheduling(client, node, allowScheduling=True)
    wait_new_replica_ready(client, volume_name, replica_names)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_hard_anti_affinity_offline_rebuild(client, volume_name):  # NOQA
    """
    Test that volumes with Hard Anti-Affinity can build new replicas during
    the attaching process once a valid node is available.

    Once a new replica has been built as part of the attaching process, the
    volume should be Healthy again.

    1. Create a volume and attach to the current node
    2. Generate and write `data` to the volume.
    3. Set `soft anti-affinity` to false
    4. Disable current node's scheduling.
    5. Remove the replica on the current node
        1. Verify volume will be in degraded state.
        2. Verify volume reports condition `scheduled == false`
    6. Detach the volume.
    7. Enable current node's scheduling.
    8. Attach the volume again.
    9. Wait for volume to become healthy with 3 replicas
    10. Check volume `data`
    """
    volume = create_and_check_volume(client, volume_name)
    host_id = get_self_host_id()
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3

    data = write_volume_random_data(volume)
    setting = client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(setting, value="false")
    node = client.by_id_node(host_id)
    set_node_scheduling(client, node, allowScheduling=False)
    replica_names = map(lambda replica: replica.name, volume.replicas)
    host_replica = get_host_replica(volume, host_id)

    volume.replicaRemove(name=host_replica.name)
    volume = wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)
    volume.detach()
    volume = wait_for_volume_detached(client, volume_name)
    set_node_scheduling(client, node, allowScheduling=True)
    volume.attach(hostId=host_id)
    wait_new_replica_ready(client, volume_name, replica_names)
    volume = wait_for_volume_healthy(client, volume_name)
    assert len(volume.replicas) == 3
    check_volume_data(volume, data)

    cleanup_volume(client, volume)


@pytest.mark.v2_volume_test  # NOQA
def test_replica_rebuild_per_volume_limit(client, core_api, storage_class, sts_name, statefulset):  # NOQA
    """
    Test the volume always only have one replica scheduled for rebuild

    1. Set soft anti-affinity to `true`.
    2. Create a volume with 1 replica.
    3. Attach the volume and write a few hundreds MB data to it.
    4. Scale the volume replica to 5.
    5. Constantly checking the volume replica list to make sure there should be
       only 1 replica in WO state.
    6. Wait for the volume to complete rebuilding. Then remove 4 of the 5
       replicas.
    7. Monitoring the volume replica list again.
    8. Once the rebuild was completed again, verify the data checksum.
    """
    replica_soft_anti_affinity_setting = \
        client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    client.update(replica_soft_anti_affinity_setting, value="true")

    data_path = '/data/test'
    storage_class['parameters']['numberOfReplicas'] = "1"
    vol_name, pod_name, md5sum = \
        common.prepare_statefulset_with_data_in_mb(
            client, core_api, statefulset, sts_name, storage_class,
            data_path=data_path, data_size_in_mb=DATA_SIZE_IN_MB_2)

    # Scale the volume replica to 5
    r_count = 5
    vol = client.by_id_volume(vol_name)
    vol.updateReplicaCount(replicaCount=r_count)

    vol = common.wait_for_volume_replicas_mode(client, vol_name, 'RW',
                                               replica_count=r_count)
    wait_for_volume_healthy(client, vol_name)

    # Delete 4 volume replicas
    del vol.replicas[0]
    for r in vol.replicas:
        vol.replicaRemove(name=r.name)

    r_count = 1
    common.wait_for_volume_replicas_mode(client, vol_name, 'RW',
                                         replica_count=r_count)

    assert md5sum == common.get_pod_data_md5sum(core_api, pod_name, data_path)


@pytest.mark.v2_volume_test  # NOQA
def test_replica_auto_balance_node_least_effort(client, volume_name):  # NOQA
    """
    Scenario: replica auto-balance nodes with `least_effort`.

    Given set `replica-soft-anti-affinity` to `true`.
    And set `replica-auto-balance` to `least_effort`.
    And disable scheduling for node-2.
        disable scheduling for node-3.
    And create a volume with 6 replicas.
    And attach the volume to self-node.
    And wait for the volume to be healthy.
    And write some data to the volume.
    And count replicas running on each nodes.
    And 6 replicas running on node-1.
        0 replicas running on node-2.
        0 replicas running on node-3.

    When enable scheduling for node-2.
    Then count replicas running on each nodes.
    And node-1 replica count != node-2 replica count.
        node-2 replica count != 0.
        node-3 replica count == 0.
    And loop 3 times with each wait 5 seconds and count replicas on each nodes.
        To ensure no addition scheduling is happening.
        The number of replicas running should be the same.

    When enable scheduling for node-3.
    And count replicas running on each nodes.
    And node-1 replica count != node-3 replica count.
        node-2 replica count != 0.
        node-3 replica count != 0.
    And loop 3 times with each wait 5 seconds and count replicas on each nodes.
        To ensure no addition scheduling is happening.
        The number of replicas running should be the same.

    When check the volume data.
    And volume data should be the same as written.
    """
    common.update_setting(client,
                          SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    common.update_setting(client,
                          SETTING_REPLICA_AUTO_BALANCE, "least-effort")

    n1, n2, n3 = client.list_node()
    client.update(n2, allowScheduling=False)
    client.update(n3, allowScheduling=False)

    n_replicas = 6
    volume = create_and_check_volume(client, volume_name,
                                     num_of_replicas=n_replicas)
    volume.attach(hostId=get_self_host_id())
    volume = wait_for_volume_healthy(client, volume_name)

    data = write_volume_random_data(volume)
    check_volume_data(volume, data)

    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=False)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=False)

        if n1_r_count == 6 and n2_r_count == n3_r_count == 0:
            break
        time.sleep(RETRY_INTERVAL)
    assert n1_r_count == 6
    assert n2_r_count == 0
    assert n3_r_count == 0

    client.update(n2, allowScheduling=True, evictionRequested=False)
    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=False)

        all_r_count = n1_r_count + n2_r_count + n3_r_count
        if n2_r_count != 0 and all_r_count == n_replicas:
            break
        time.sleep(RETRY_INTERVAL)
    assert n1_r_count != n2_r_count
    assert n2_r_count != 0
    assert n3_r_count == 0

    # loop 3 times and each to wait 5 seconds to ensure there is no
    # re-scheduling happening.
    for _ in range(3):
        time.sleep(5)
        assert n1_r_count == common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        assert n2_r_count == common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        assert n3_r_count == common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

    client.update(n3, allowScheduling=True, evictionRequested=False)
    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

        all_r_count = n1_r_count + n2_r_count + n3_r_count
        if n3_r_count != 0 and all_r_count == n_replicas:
            break
        time.sleep(RETRY_INTERVAL)
    assert n1_r_count != n3_r_count
    assert n2_r_count != 0
    assert n3_r_count != 0

    # loop 3 times and each to wait 5 seconds to ensure there is no
    # re-scheduling happening.
    for _ in range(3):
        time.sleep(5)
        assert n1_r_count == common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        assert n2_r_count == common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        assert n3_r_count == common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

    volume = client.by_id_volume(volume_name)
    check_volume_data(volume, data)


@pytest.mark.v2_volume_test  # NOQA
@pytest.mark.flaky(reruns=3)
def test_replica_auto_balance_node_best_effort(client, volume_name):  # NOQA
    """
    Scenario: replica auto-balance nodes with `best_effort`.

    Given set `replica-soft-anti-affinity` to `true`.
    And set `replica-auto-balance` to `best_effort`.
    And disable scheduling for node-2.
        disable scheduling for node-3.
    And create a volume with 6 replicas.
    And attach the volume to self-node.
    And wait for the volume to be healthy.
    And write some data to the volume.
    And count replicas running on each node.
    And 6 replicas running on node-1.
        0 replicas running on node-2.
        0 replicas running on node-3.

    When enable scheduling for node-2.
    And count replicas running on each node.
    Then 3 replicas running on node-1.
         3 replicas running on node-2.
         0 replicas running on node-3.
    And loop 3 times with each wait 5 seconds and count replicas on each nodes.
        To ensure no addition scheduling is happening.
        3 replicas running on node-1.
        3 replicas running on node-2.
        0 replicas running on node-3.

    When enable scheduling for node-3.
    And count replicas running on each node.
    Then 2 replicas running on node-1.
         2 replicas running on node-2.
         2 replicas running on node-3.
    And loop 3 times with each wait 5 seconds and count replicas on each nodes.
        To ensure no addition scheduling is happening.
        2 replicas running on node-1.
        2 replicas running on node-2.
        2 replicas running on node-3.

    When check the volume data.
    And volume data should be the same as written.
    """
    common.update_setting(client,
                          SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    common.update_setting(client,
                          SETTING_REPLICA_AUTO_BALANCE, "best-effort")

    n1, n2, n3 = client.list_node()
    client.update(n2, allowScheduling=False)
    client.update(n3, allowScheduling=False)

    n_replicas = 6
    volume = create_and_check_volume(client, volume_name,
                                     num_of_replicas=n_replicas)
    volume.attach(hostId=get_self_host_id())
    volume = wait_for_volume_healthy(client, volume_name)

    data = write_volume_random_data(volume)
    check_volume_data(volume, data)

    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

        if n1_r_count == 6 and n2_r_count == n3_r_count == 0:
            break
        time.sleep(RETRY_INTERVAL)
    assert n1_r_count == 6
    assert n2_r_count == 0
    assert n3_r_count == 0

    client.update(n2, allowScheduling=True, evictionRequested=False)
    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

        if n1_r_count == 3 and n2_r_count == 3 and n3_r_count == 0:
            break
        time.sleep(RETRY_INTERVAL)
    assert n1_r_count == 3
    assert n2_r_count == 3
    assert n3_r_count == 0

    # loop 3 times and each to wait 5 seconds to ensure there is no
    # re-scheduling happening.
    for _ in range(3):
        time.sleep(5)
        assert n1_r_count == common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        assert n2_r_count == common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        assert n3_r_count == common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

    client.update(n3, allowScheduling=True, evictionRequested=False)
    for _ in range(RETRY_COUNTS):
        n1_r_count = common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        n2_r_count = common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        n3_r_count = common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

        if n1_r_count == n2_r_count == n3_r_count == 2:
            break
        time.sleep(RETRY_INTERVAL_LONG)
    assert n1_r_count == 2
    assert n2_r_count == 2
    assert n3_r_count == 2

    # loop 3 times and each to wait 5 seconds to ensure there is no
    # re-scheduling happening.
    for _ in range(3):
        time.sleep(5)
        assert n1_r_count == common.get_host_replica_count(
            client, volume_name, n1.name, chk_running=True)
        assert n2_r_count == common.get_host_replica_count(
            client, volume_name, n2.name, chk_running=True)
        assert n3_r_count == common.get_host_replica_count(
            client, volume_name, n3.name, chk_running=True)

    volume = client.by_id_volume(volume_name)
    check_volume_data(volume, data)


def test_replica_auto_balance_disk_in_pressure(client, core_api, apps_api, volume_name, statefulset, storage_class):  # NOQA
    """
    Scenario: Test replica auto balance disk in pressure

    Description: This test simulates a scenario where a disk reaches a certain
                 pressure threshold (80%), triggering the replica auto balance
                 to rebuild the replicas to another disk with enough available
                 space. Replicas should not be rebuilted at the same time.

    Issue: https://github.com/longhorn/longhorn/issues/4105

    Given setting "replica-soft-anti-affinity" is "false"
    And setting "replica-auto-balance-disk-pressure-percentage" is "80"
    And new 1Gi disk 1 is created on self node
        new 1Gi disk 2 is created on self node
    And disk scheduling is disabled for disk 1 on self node
        disk scheduling is disabled for default disk on self node
    And node scheduling is disabled for all nodes except self node
    And new storageclass is created with `numberOfReplicas: 1`
    And statefulset 0 is created with 1 replicaset
        statefulset 1 is created with 1 replicaset
        statefulset 2 is created with 1 replicaset
    And all statefulset volume replicas are scheduled on disk 1
    And data is written to all statefulset volumes until disk 1 is pressured
    And disk 1 pressure is exceeded threshold (80%)

    When enable disk scheduling for disk 1 on self node
    And update setting "replica-auto-balance" to "best-effort"

    Then at least 1 replicas should be rebuilt on disk 2
    And at least 1 replica should not be rebuilt on disk 2
    And disk 1 should be below disk pressure threshold (80%)
    And all statefulset volume data should be intact
    """
    # Set the "replica-soft-anti-affinity" to "true".
    update_setting(client, SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "false")

    # Set the "replica-auto-balance-disk-pressure-percentage" to 80%.
    disk_pressure_percentage = 80
    update_setting(client,
                   SETTING_REPLICA_AUTO_BALANCE_DISK_PRESSURE_PERCENTAGE,
                   str(disk_pressure_percentage))

    self_host_id = get_self_host_id()
    disk_size = Gi
    disk1_name = "test-disk1"
    disk2_name = "test-disk2"

    def _create_disk_on_self_host(client, disk_name, allow_scheduling):
        node = client.by_id_node(self_host_id)
        update_disks = get_update_disks(node.disks)
        disk_path = create_host_disk(client, disk_name,
                                     str(disk_size), self_host_id)
        update_disks[disk_name] = {"path": disk_path,
                                   "allowScheduling": allow_scheduling}
        update_node_disks(client, node.name, disks=update_disks, retry=True)
        node = wait_for_disk_update(client, self_host_id, len(update_disks))
        assert len(node.disks) == len(update_disks)

    def _set_host_disk_allow_scheduling(client, disk_name):
        node = client.by_id_node(self_host_id)
        update_disks = get_update_disks(node.disks)

        for name, disk in update_disks.items():
            if name == disk_name:
                disk.allowScheduling = True

        update_node_disks(client, node.name, disks=update_disks, retry=True)
        node = wait_for_disk_update(client, self_host_id, len(update_disks))
        assert len(node.disks) == len(update_disks)

    def _disable_default_disk_on_self_host(client):
        node = client.by_id_node(self_host_id)
        update_disks = get_update_disks(node.disks)

        for _, disk in update_disks.items():
            if disk.path == DEFAULT_DISK_PATH:
                disk.allowScheduling = False

        update_node_disks(client, node.name, disks=update_disks, retry=True)
        node = wait_for_disk_update(client, self_host_id, len(update_disks))
        assert len(node.disks) == len(update_disks)

    def _disable_node_scheduling_except_self_host(client):
        nodes = client.list_node()
        for node in nodes:
            if node.name != self_host_id:
                client.update(node, allowScheduling=False)
                wait_for_node_update(client, node.id, "allowScheduling", False)

    def _get_disk_storage_available(client, disk_name):
        node = client.by_id_node(self_host_id)
        for name, disk in node.disks.items():
            if name == disk_name:
                return disk.storageAvailable
        assert False, f"Cannot find disk {disk_name} on node {self_host_id}."

    def _create_statefulset(statefulset, statefulset_name,
                            storage_class, volume_size, replicas):
        statefulset['metadata']['name']\
            = statefulset['spec']['selector']['matchLabels']['app']\
            = statefulset['spec']['serviceName']\
            = statefulset['spec']['template']['metadata']['labels']['app']\
            = statefulset_name

        statefulset['spec']['replicas'] = replicas

        volume_claim_template = statefulset['spec']['volumeClaimTemplates'][0]
        volume_claim_template['spec']['storageClassName']\
            = storage_class['metadata']['name']
        volume_claim_template['spec']['resources']['requests']['storage']\
            = size_to_string(volume_size)

        create_and_wait_statefulset(statefulset)

    def _wait_for_storage_usage_reach_disk_pressured_percentage(
            client, node_id, disk_name, disk_pressure_percentage,
            is_freed=False):
        node = client.by_id_node(node_id)

        expected_avaiable_percentage = 100 - disk_pressure_percentage

        for _ in range(RETRY_COUNTS):
            time.sleep(RETRY_INTERVAL)

            node = client.by_id_node(node_id)

            check_disk = None
            for name, disk in node.disks.items():
                if name == disk_name:
                    check_disk = disk
                    break

            assert check_disk is not None, \
                f"Cannot find disk {disk_name} on node {node_id}."

            if check_disk.storageAvailable == check_disk.storageScheduled:
                continue

            actual_avaiable_percentage = \
                check_disk.storageAvailable / check_disk.storageMaximum * 100

            if not is_freed:
                if actual_avaiable_percentage < expected_avaiable_percentage:
                    print(f"{disk_name} in pressure: "
                          f"{actual_avaiable_percentage}% available")
                    return
            else:
                if actual_avaiable_percentage > expected_avaiable_percentage:
                    print(f"{disk_name} not in pressure: "
                          f"{actual_avaiable_percentage}% available")
                    return

        condition = "is not" if not is_freed else "is"
        assert False, \
            f"Disk {disk_name} {condition} in pressure." \
            f"Expected below {expected_avaiable_percentage}%." \
            f"Actually used {actual_avaiable_percentage}%."

    def _cleanup(client, volume_names, statefulset_names):
        for _volume_name in volume_names:
            cleanup_volume_by_name(client, _volume_name)

        for _statefulset_name in statefulset_names:
            _statefulset = {
                'metadata': {
                    'name': _statefulset_name,
                    'namespace': 'default'
                }
            }
            delete_statefulset(apps_api, _statefulset)

        for _volume_name in volume_names:
            wait_for_volume_delete(client, _volume_name)

        cleanup_disks_on_node(client, self_host_id, disk1_name, disk2_name)

    # Create new disks and disable scheduling on disk 2.
    _create_disk_on_self_host(client, disk1_name, allow_scheduling=True)
    _create_disk_on_self_host(client, disk2_name, allow_scheduling=False)

    # Disable scheduling on default disk of self host and other nodes.
    _disable_default_disk_on_self_host(client)
    _disable_node_scheduling_except_self_host(client)

    # Create new storage class with "numberOfReplicas" set to 1.
    storage_class['parameters']['numberOfReplicas'] = "1"
    create_storage_class(storage_class)

    # Expect 3 volumes to be created later, each with 1 replica.
    expected_replica_count = 3

    # Calculate the size of each volume based on the available storage of
    # disk 1.
    disk_storage_available = _get_disk_storage_available(client, disk1_name)
    volume_size = int(disk_storage_available/expected_replica_count)

    # Create 3 statefulsets with 1 replica each.
    statefulset_names = [f'sts-{i}' for i in range(expected_replica_count)]
    for _statefulset_name in statefulset_names:
        _create_statefulset(statefulset, _statefulset_name,
                            storage_class, volume_size,
                            replicas=1)

    # Verify that all volumes are created with 1 replica.
    claims = core_api.list_namespaced_persistent_volume_claim(
        namespace='default')
    volume_names = [claim.spec.volume_name for claim in claims.items]
    assert len(volume_names) == expected_replica_count, \
        f"Expected {expected_replica_count} volumes."

    # Verify that all replicas are scheduled on disk 1.
    node = client.by_id_node(self_host_id)
    disks = node.disks
    scheduled_disk_name = ""
    for _volume_name in volume_names:
        for name, disk in disks.items():
            for scheduled_replica, _ in disk.scheduledReplica.items():
                if scheduled_replica.startswith(_volume_name):
                    scheduled_disk_name = name
                    break
        assert scheduled_disk_name == disk1_name, \
            f"Replica scheduled on wrong disk {scheduled_disk_name}."

    # Get the node disk of disk 1.
    scheduled_disk = None
    for name, disk in node.disks.items():
        if name == scheduled_disk_name:
            scheduled_disk = disk
            break
    assert scheduled_disk is not None, \
        f"Failed to get node disk {scheduled_disk_name}."

    storage_maximum = scheduled_disk.storageMaximum
    storage_available = scheduled_disk.storageAvailable

    # Calculate the total data size to add to simulate disk pressure.
    target_disk_size_usage = storage_maximum * disk_pressure_percentage / 100
    current_useage = storage_maximum - storage_available
    target_data_size = target_disk_size_usage - current_useage

    # Calculate the data size to write to each volume.
    data_size = math.ceil(target_data_size / len(volume_names))
    assert data_size != 0, \
        f"Failed to get data size for disk {scheduled_disk_name}."

    data_size_mb = math.ceil(data_size / 1024 / 1024)
    pod_md5sums = {}

    # Write data to each volume and get the MD5 checksum..
    for _statefulset_name in statefulset_names:
        pod_name = _statefulset_name + '-0'
        write_pod_volume_random_data(core_api, pod_name, "/data/test",
                                     data_size_mb)

        md5sum = get_pod_data_md5sum(core_api, pod_name, "/data/test")

        pod_md5sums[pod_name] = md5sum

    # Wait for storage usage to reach the disk pressure percentage.
    _wait_for_storage_usage_reach_disk_pressured_percentage(
        client, self_host_id, disk1_name, disk_pressure_percentage)

    # Allow scheduling on disk2.
    _set_host_disk_allow_scheduling(client, disk2_name)

    # Set "replica-auto-balance" to "best-effort" to trigger rebuild.
    update_setting(client, SETTING_REPLICA_AUTO_BALANCE, "best-effort")

    # Wait for the volume to be rebuilt.
    actual_rebuilt, actual_not_rebuilt = 0, 0
    for _volume_name in volume_names:
        try:
            wait_for_volume_replica_rebuilt_on_same_node_different_disk(
                client, self_host_id, _volume_name, scheduled_disk_name
            )
            actual_rebuilt += 1
        except AssertionError:
            print(f"Volume {_volume_name} not rebuilt")
            actual_not_rebuilt += 1
    # There can be a delay up to 30 seconds for the disk storage usage to
    # reflect after a replica is removed from disk 1. This can cause an
    # additional replica to be rebuilt on disk 2 before the node controller's
    # disk monitor detects the space change on disk 1.
    assert actual_rebuilt >= 1, \
        f"Expected at least 1 volume replica rebuilt.\n"\
        f"Actual {actual_rebuilt} volume replica rebuilt."
    assert actual_not_rebuilt >= 1, \
        f"Expected at least 1 volume replica not rebuilt.\n"\
        f"Actual {actual_not_rebuilt} volume replica not rebuilt."

    _wait_for_storage_usage_reach_disk_pressured_percentage(
        client, self_host_id, disk1_name, disk_pressure_percentage,
        is_freed=True
    )

    # Verify data integrity by checking MD5 checksum.
    for pod_name, md5sum in pod_md5sums.items():
        current_md5sum = get_pod_data_md5sum(core_api, pod_name, "/data/test")
        assert md5sum == current_md5sum, \
            f"Data in pod {pod_name} doesn't match."

    _cleanup(client, volume_names, statefulset_names)


@pytest.mark.skip(reason="corner case") # NOQA
def test_replica_auto_balance_with_data_locality(client, volume_name):  # NOQA
    """
    Scenario: replica auto-balance should not cause rebuild loop.
              - replica auto-balance set to `best-effort`
              - volume data locality set to `best-effort`
              - volume has 1 replica

    Issue: https://github.com/longhorn/longhorn/issues/4761

    Given no existing volume in the cluster.
    And set `replica-auto-balance` to `best-effort`.
    And create a volume:
        - set data locality to `best-effort`
        - 1 replica

    When attach the volume to self-node.
    And wait for the volume to be healthy.
    Then the only volume replica should be already on the self-node or
         get rebuilt one time onto the self-node.
    And volume have 1 replica only and it should be on the self-node.
         - check 15 times with 1 second wait interval

    When repeat the test for 10 times.
    Then should pass.
    """
    # Repeat tests since there is a possibility that we might miss this.
    # Because when the replica is built onto the correct node the first time,
    # there will be no rebuild by data locality, hence we will not see the
    # loop.
    for i in range(10):
        replica_auto_balance_with_data_locality_test(
            client, f'{volume_name}-{i}'
        )


def replica_auto_balance_with_data_locality_test(client, volume_name):  # NOQA
    common.cleanup_all_volumes(client)

    common.update_setting(client,
                          SETTING_REPLICA_AUTO_BALANCE, "best-effort")

    self_node = get_self_host_id()
    number_of_replicas = 1
    volume = client.create_volume(name=volume_name,
                                  size=str(200 * Mi),
                                  numberOfReplicas=number_of_replicas,
                                  dataLocality="best-effort",
                                  dataEngine=DATA_ENGINE)
    volume = common.wait_for_volume_detached(client, volume_name)

    volume.attach(hostId=self_node)
    volume = wait_for_volume_healthy(client, volume_name)

    # wait for replica to be on the self_node
    for _ in range(30):
        volume = client.by_id_volume(volume_name)
        if len(volume.replicas) == number_of_replicas and \
                volume.replicas[0]['hostId'] == self_node:
            break
        try:
            if len(volume.replicas) == number_of_replicas + 1:
                is_rebuilded = True
            assert len(volume.replicas) == number_of_replicas
            assert volume.replicas[0]['hostId'] == self_node
            assert volume[VOLUME_FIELD_ROBUSTNESS] == VOLUME_ROBUSTNESS_HEALTHY
            break
        except AssertionError:
            # Breaking this for loop asserts we are only checking the result
            # of the first rebuild. Without this break, the rebuild could
            # happen multiple times, and one of the rebuilt replica names
            # eventually ends up alphabetically smaller. Hence the miss-catch
            # the looping issue.
            if is_rebuilded and len(volume.replicas) == number_of_replicas:
                break
            time.sleep(RETRY_INTERVAL)

    assert len(volume.replicas) == number_of_replicas, \
        f"Unexpected replica count for volume {volume_name}.\n"
    assert volume.replicas[0]['hostId'] == self_node, \
        f"Unexpected replica host ID for volume {volume_name}.\n"
    assert volume[VOLUME_FIELD_ROBUSTNESS] == VOLUME_ROBUSTNESS_HEALTHY

    # loop to assert there sholud be no more replica rebuildings
    for _ in range(15):
        time.sleep(RETRY_INTERVAL)

        volume = client.by_id_volume(volume_name)
        assert len(volume.replicas) == number_of_replicas, \
            f"Not expecting scheduling for volume {volume_name}.\n"
        assert volume.replicas[0]['hostId'] == self_node, \
            f"Unexpected replica host ID for volume {volume_name}.\n" \
            f"Expect={self_node}\n" \
            f"Got={volume.replicas[0]['hostId']}\n"


def test_replica_auto_balance_disabled_volume_spec_enabled(client, volume_name):  # NOQA
    """
    Scenario: replica should auto-balance individual volume when
              global setting `replica-auto-balance` is `disabled` and
              volume spec `replicaAutoBalance` is `least_effort`.

    Given set `replica-soft-anti-affinity` to `true`.
    And set `replica-auto-balance` to `disabled`.
    And disable scheduling for node-2.
        disable scheduling for node-3.
    And create volume-1 with 3 replicas.
        create volume-2 with 3 replicas.
    And set volume-2 spec `replicaAutoBalance` to `least-effort`.
    And attach volume-1 to self-node.
        attach volume-2 to self-node.
    And wait for volume-1 to be healthy.
        wait for volume-2 to be healthy.
    And count volume-1 replicas running on each node.
    And 3 replicas running on node-1.
        0 replicas running on node-2.
        0 replicas running on node-3.
    And count volume-2 replicas running on each node.
    And 3 replicas running on node-1.
        0 replicas running on node-2.
        0 replicas running on node-3.
    And write some data to volume-1.
        write some data to volume-2.

    When enable scheduling for node-2.
         enable scheduling for node-3.

    Then count volume-1 replicas running on each node.
    And 3 replicas running on node-1.
        0 replicas running on node-2.
        0 replicas running on node-3.
    And count volume-2 replicas running on each node.
    And 1 replicas running on node-1.
        1 replicas running on node-2.
        1 replicas running on node-3.
    And volume-1 data should be the same as written.
    And volume-2 data should be the same as written.
    """
    common.update_setting(client,
                          SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    common.update_setting(client,
                          SETTING_REPLICA_AUTO_BALANCE, "disabled")

    n1, n2, n3 = client.list_node()
    client.update(n2, allowScheduling=False)
    client.update(n3, allowScheduling=False)

    n_replicas = 3
    v1_name = volume_name + "-1"
    v2_name = volume_name + "-2"

    v1 = create_and_check_volume(client, v1_name,
                                 num_of_replicas=n_replicas)
    v2 = create_and_check_volume(client, v2_name,
                                 num_of_replicas=n_replicas)

    v2.updateReplicaAutoBalance(ReplicaAutoBalance="least-effort")
    common.wait_for_volume_replica_auto_balance_update(
        client, v2_name, "least-effort"
    )

    self_node = get_self_host_id()
    v1.attach(hostId=self_node)
    v2.attach(hostId=self_node)

    v1 = wait_for_volume_healthy(client, v1_name)
    v2 = wait_for_volume_healthy(client, v2_name)

    for _ in range(RETRY_COUNTS):
        v1n1_r_count = common.get_host_replica_count(
            client, v1_name, n1.name, chk_running=True)
        v1n2_r_count = common.get_host_replica_count(
            client, v1_name, n2.name, chk_running=True)
        v1n3_r_count = common.get_host_replica_count(
            client, v1_name, n3.name, chk_running=True)

        if v1n1_r_count == n_replicas and v1n2_r_count == v1n3_r_count == 0:
            break
        time.sleep(RETRY_INTERVAL)
    assert v1n1_r_count == n_replicas
    assert v1n2_r_count == 0
    assert v1n3_r_count == 0

    for _ in range(RETRY_COUNTS):
        v2n1_r_count = common.get_host_replica_count(
            client, v2_name, n1.name, chk_running=True)
        v2n2_r_count = common.get_host_replica_count(
            client, v2_name, n2.name, chk_running=True)
        v2n3_r_count = common.get_host_replica_count(
            client, v2_name, n3.name, chk_running=True)

        if v2n1_r_count == n_replicas and v2n2_r_count == v2n3_r_count == 0:
            break
        time.sleep(RETRY_INTERVAL)
    assert v2n1_r_count == n_replicas
    assert v2n2_r_count == 0
    assert v2n3_r_count == 0

    d1 = write_volume_random_data(v1)
    d2 = write_volume_random_data(v2)
    check_volume_data(v1, d1)
    check_volume_data(v2, d2)

    client.update(n2, allowScheduling=True, evictionRequested=False)
    client.update(n3, allowScheduling=True, evictionRequested=False)

    assert v1n1_r_count == common.get_host_replica_count(
        client, v1_name, n1.name, chk_running=True)
    assert v1n2_r_count == common.get_host_replica_count(
        client, v1_name, n2.name, chk_running=True)
    assert v1n3_r_count == common.get_host_replica_count(
        client, v1_name, n3.name, chk_running=True)

    for _ in range(RETRY_COUNTS):
        v2n1_r_count = common.get_host_replica_count(
            client, v2_name, n1.name, chk_running=True)
        v2n2_r_count = common.get_host_replica_count(
            client, v2_name, n2.name, chk_running=True)
        v2n3_r_count = common.get_host_replica_count(
            client, v2_name, n3.name, chk_running=True)

        if v2n1_r_count == v2n2_r_count == v2n3_r_count == 1:
            break
        time.sleep(RETRY_INTERVAL)
    assert v2n1_r_count == 1
    assert v2n2_r_count == 1
    assert v2n3_r_count == 1

    check_volume_data(v1, d1)
    check_volume_data(v2, d2)


@pytest.mark.v2_volume_test  # NOQA
def test_data_locality_basic(client, core_api, volume_name, pod, settings_reset):  # NOQA
    """
    Test data locality basic feature

    Context:

    Data Locality feature allows users to have an option to keep a local
    replica on the same node as the consuming pod.
    Longhorn is currently supporting 2 modes:
    - disabled: Longhorn does not try to keep a local replica
    - best-effort: Longhorn try to keep a local replica

    See manual tests at:
    https://github.com/longhorn/longhorn/issues/1045#issuecomment-680706283

    Steps:

    Case 1: Test that Longhorn builds a local replica on the engine node

    1. Create a volume(1) with 1 replica and dataLocality set to disabled
    2. Find node where the replica is located on.
       Let's call the node is replica-node
    3. Attach the volume to a node different than replica-node.
       Let call the node is engine-node
    4. Write 200MB data to volume(1)
    5. Use a retry loop to verify that Longhorn does not create
       a replica on the engine-node
    6. Update dataLocality to best-effort for volume(1)
    7. Use a retry loop to verify that Longhorn creates and rebuilds
       a replica on the engine-node and remove the other replica
    8. detach the volume(1) and attach it to a different node.
       Let's call the new node is new-engine-node and the old
       node is old-engine-node
    9. Wait for volume(1) to finish attaching
    10. Use a retry loop to verify that Longhorn creates and rebuilds
       a replica on the new-engine-node and remove the replica on
       old-engine-node

    Case 2: Test that Longhorn prioritizes deleting replicas on the same node

    1. Add the tag AVAIL to node-1 and node-2
    2. Set node soft anti-affinity to `true`.
    3. Create a volume(2) with 3 replicas and dataLocality set to best-effort
    4. Use a retry loop to verify that all 3 replicas are on node-1 and
        node-2, no replica is on node-3
    5. Attach volume(2) to node-3
    6. User a retry loop to verify that there is no replica on node-3 and
        we can still read/write to volume(2)
    7. Find the node which contains 2 replicas.
        Let call the node is most-replica-node
    8. Set the replica count to 2 for volume(2)
    9. Verify that Longhorn remove one replica from most-replica-node

    Case 3: Test that the volume is not corrupted if there is an unexpected
    detachment during building local replica

    1. Remove the tag AVAIL from node-1 and node-2
       Set node soft anti-affinity to `false`.
    2. Create a volume(3) with 1 replicas and dataLocality set to best-effort
    3. Attach volume(3) to node-3.
    4. Use a retry loop to verify that volume(3) has only 1 replica on node-3
    5. Write 2GB data to volume(3)
    6. Detach volume(3)
    7. Attach volume(3) to node-1
    8. Use a retry loop to:
        Wait until volume(3) finishes attaching.
        Wait until Longhorn start rebuilding a replica on node-1
        Immediately detach volume(3)
    9. Verify that the replica on node-1 is in ERR state.
    10. Attach volume(3) to node-1
    11. Wait until volume(3) finishes attaching.
    12. Use a retry loop to verify the Longhorn cleanup the ERR replica,
        rebuild a new replica on node-1, and remove the replica on node-3

    Case 4: Make sure failed to schedule local replica doesn't block the
    the creation of other replicas.

    1. Disable scheduling for node-3
    2. Create a vol with 1 replica, `dataLocality = best-effort`.
        The replica is scheduled on a node (say node-1)
    3. Attach vol to node-3. There is a fail-to-schedule
        replica with Spec.HardNodeAffinity=node-3
    4. Increase numberOfReplica to 3. Verify that the replica set contains:
        one on node-1, one on node-2,  one failed replica
        with Spec.HardNodeAffinity=node-3.
    5. Decrease numberOfReplica to 2. Verify that the replica set contains:
        one on node-1, one on node-2,  one failed replica
        with Spec.HardNodeAffinity=node-3.
    6. Decrease numberOfReplica to 1. Verify that the replica set contains:
        one on node-1 or node-2,  one failed replica
        with Spec.HardNodeAffinity=node-3.
    7. Decrease numberOfReplica to 2. Verify that the replica set contains:
        one on node-1, one on node-2, one failed replica
        with Spec.HardNodeAffinity=node-3.
    8. Turn off data locality by set `dataLocality=disabled` for the vol.
        Verify that the replica set contains: one on node-1, one on node-2

    9. clean up
    """

    # Case 1: Test that Longhorn builds a local replica on the engine node

    nodes = client.list_node()

    default_data_locality_setting = \
        client.by_id_setting(SETTING_DEFAULT_DATA_LOCALITY)
    try:
        client.update(default_data_locality_setting, value="disabled")
    except Exception as e:
        print("Exception when update Default Data Locality setting",
              default_data_locality_setting, e)

    volume1_name = volume_name + "-1"
    volume1_size = str(500 * Mi)
    volume1_data_path = "/data/test"
    pv1_name = volume1_name + "-pv"
    pvc1_name = volume1_name + "-pvc"
    pod1_name = volume1_name + "-pod"
    pod1 = pod

    pod1['metadata']['name'] = pod1_name

    volume1 = create_and_check_volume(client, volume1_name,
                                      num_of_replicas=1,
                                      size=volume1_size)

    volume1 = client.by_id_volume(volume1_name)
    create_pv_for_volume(client, core_api, volume1, pv1_name)
    create_pvc_for_volume(client, core_api, volume1, pvc1_name)

    volume1 = client.by_id_volume(volume1_name)
    volume1_replica_node = volume1.replicas[0]['hostId']

    volume1_attached_node = None
    for node in nodes:
        if node.name != volume1_replica_node:
            volume1_attached_node = node.name
            break

    assert volume1_attached_node is not None

    pod1['spec']['volumes'] = [{
        "name": "pod-data",
        "persistentVolumeClaim": {
            "claimName": pvc1_name
        }
    }]

    pod1['spec']['nodeSelector'] = \
        {"kubernetes.io/hostname": volume1_attached_node}
    create_and_wait_pod(core_api, pod1)

    write_pod_volume_random_data(core_api, pod1_name,
                                 volume1_data_path, DATA_SIZE_IN_MB_2)

    for i in range(10):
        volume1 = client.by_id_volume(volume1_name)
        assert len(volume1.replicas) == 1
        assert volume1.replicas[0]['hostId'] != volume1_attached_node
        time.sleep(1)

    volume1 = client.by_id_volume(volume1_name)
    volume1.updateDataLocality(dataLocality="best-effort")

    for _ in range(RETRY_COUNTS):
        volume1 = client.by_id_volume(volume1_name)
        assert volume1[VOLUME_FIELD_ROBUSTNESS] == VOLUME_ROBUSTNESS_HEALTHY
        if len(volume1.replicas) == 1 and \
                volume1.replicas[0]['hostId'] == volume1_attached_node:
            break
        time.sleep(RETRY_INTERVAL)
    assert len(volume1.replicas) == 1
    assert volume1.replicas[0]['hostId'] == volume1_attached_node

    delete_and_wait_pod(core_api, pod1_name)
    volume1 = wait_for_volume_detached(client, volume1_name)

    volume1_replica_node = volume1.replicas[0]['hostId']

    volume1_attached_node = None
    for node in nodes:
        if node.name != volume1_replica_node:
            volume1_attached_node = node.name
            break

    assert volume1_attached_node is not None

    pod1['spec']['nodeSelector'] = \
        {"kubernetes.io/hostname": volume1_attached_node}
    create_and_wait_pod(core_api, pod1)
    for _ in range(RETRY_COUNTS):
        volume1 = client.by_id_volume(volume1_name)
        assert volume1[VOLUME_FIELD_ROBUSTNESS] == VOLUME_ROBUSTNESS_HEALTHY
        if len(volume1.replicas) == 1 and \
                volume1.replicas[0]['hostId'] == volume1_attached_node:
            break
        time.sleep(RETRY_INTERVAL)
    assert len(volume1.replicas) == 1
    assert volume1.replicas[0]['hostId'] == volume1_attached_node
    delete_and_wait_pod(core_api, pod1_name)
    wait_for_volume_detached(client, volume1_name)

    # Case 2: Test that Longhorn prioritizes deleting replicas on the same node

    node1 = nodes[0]
    node2 = nodes[1]
    node3 = nodes[2]

    client.update(node1, allowScheduling=True, tags=["AVAIL"])
    client.update(node2, allowScheduling=True, tags=["AVAIL"])

    replica_node_soft_anti_affinity_setting = \
        client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    try:
        client.update(replica_node_soft_anti_affinity_setting,
                      value="true")
    except Exception as e:
        print("Exception when update "
              "Replica Node Level Soft Anti-Affinity setting",
              replica_node_soft_anti_affinity_setting, e)

    volume2_name = volume_name + "-2"
    volume2_size = str(500 * Mi)
    pv2_name = volume2_name + "-pv"
    pvc2_name = volume2_name + "-pvc"
    pod2_name = volume2_name + "-pod"
    pod2 = pod

    pod2['metadata']['name'] = pod2_name

    volume2 = client.create_volume(name=volume2_name,
                                   size=volume2_size,
                                   numberOfReplicas=3,
                                   nodeSelector=["AVAIL"],
                                   dataLocality="best-effort",
                                   dataEngine=DATA_ENGINE)

    volume2 = wait_for_volume_detached(client, volume2_name)
    volume2 = client.by_id_volume(volume2_name)
    create_pv_for_volume(client, core_api, volume2, pv2_name)
    create_pvc_for_volume(client, core_api, volume2, pvc2_name)

    volume2 = client.by_id_volume(volume2_name)

    pod2['spec']['volumes'] = [{
        "name": "pod-data",
        "persistentVolumeClaim": {
            "claimName": pvc2_name
        }
    }]

    pod2['spec']['nodeSelector'] = {"kubernetes.io/hostname": node3.name}
    create_and_wait_pod(core_api, pod2)

    volume2 = wait_for_volume_healthy(client, volume2_name)

    for replica in volume2.replicas:
        assert replica["hostId"] != node3.name

    volume2.updateReplicaCount(replicaCount=2)

    # 2 Healthy replicas and 1 replica failed to schedule
    # The failed to schedule replica is the local replica on node3
    volume2 = wait_for_volume_replica_count(client, volume2_name, 3)
    volume2 = client.by_id_volume(volume2_name)

    volume2_healthy_replicas = []
    for replica in volume2.replicas:
        if replica.running is True:
            volume2_healthy_replicas.append(replica)

    assert len(volume2_healthy_replicas) == 2

    volume2_rep1 = volume2_healthy_replicas[0]
    volume2_rep2 = volume2_healthy_replicas[1]
    assert volume2_rep1["hostId"] != volume2_rep2["hostId"]
    delete_and_wait_pod(core_api, pod2_name)
    wait_for_volume_detached(client, volume2_name)

    # Case 3: Test that the volume is not corrupted if there is an unexpected
    # detachment during building local replica

    client.update(node1, allowScheduling=True, tags=[])
    client.update(node2, allowScheduling=True, tags=[])

    replica_node_soft_anti_affinity_setting = \
        client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    try:
        client.update(replica_node_soft_anti_affinity_setting,
                      value="false")
    except Exception as e:
        print("Exception when update "
              "Replica Node Level Soft Anti-Affinity setting",
              replica_node_soft_anti_affinity_setting, e)

    volume3_name = volume_name + "-3"
    volume3_size = str(4 * Gi)
    volume3_data_path = "/data/test"
    pv3_name = volume3_name + "-pv"
    pvc3_name = volume3_name + "-pvc"
    pod3_name = volume3_name + "-pod"
    pod3 = pod

    pod3['metadata']['name'] = pod3_name

    volume3 = client.create_volume(name=volume3_name,
                                   size=volume3_size,
                                   numberOfReplicas=1,
                                   dataEngine=DATA_ENGINE)

    volume3 = wait_for_volume_detached(client, volume3_name)
    volume3 = client.by_id_volume(volume3_name)
    create_pv_for_volume(client, core_api, volume3, pv3_name)
    create_pvc_for_volume(client, core_api, volume3, pvc3_name)

    volume3 = client.by_id_volume(volume3_name)

    pod3['spec']['volumes'] = [{
        "name": "pod-data",
        "persistentVolumeClaim": {
            "claimName": pvc3_name
        }
    }]

    pod3['spec']['nodeSelector'] = {"kubernetes.io/hostname": node3.name}
    create_and_wait_pod(core_api, pod3)
    volume3 = wait_for_volume_healthy(client, volume3_name)

    write_pod_volume_random_data(core_api, pod3_name,
                                 volume3_data_path, 2 * Gi)

    volume3.updateDataLocality(dataLocality="best-effort")
    volume3 = client.by_id_volume(volume3_name)

    if volume3.replicas[0]['hostId'] != node3.name:
        wait_for_rebuild_start(client, volume3_name)
        volume3 = client.by_id_volume(volume3_name)
        assert len(volume3.replicas) == 2
        wait_for_rebuild_complete(client, volume3_name)

    volume3 = wait_for_volume_replica_count(client, volume3_name, 1)
    assert volume3.replicas[0]["hostId"] == node3.name

    delete_and_wait_pod(core_api, pod3_name)
    wait_for_volume_detached(client, volume3_name)

    pod3['spec']['nodeSelector'] = {"kubernetes.io/hostname": node1.name}
    create_and_wait_pod(core_api, pod3)

    wait_for_rebuild_start(client, volume3_name)
    crash_engine_process_with_sigkill(client, core_api, volume3_name)
    delete_and_wait_pod(core_api, pod3_name)
    wait_for_volume_detached(client, volume3_name)
    volume3 = client.by_id_volume(volume3_name)
    assert len(volume3.replicas) == 1
    assert volume3.replicas[0]["hostId"] == node3.name, \
        f"expect the only replica of volume3 {volume3} is on {node3.name}"

    create_and_wait_pod(core_api, pod3)
    wait_for_rebuild_start(client, volume3_name)
    volume3 = client.by_id_volume(volume3_name)
    assert len(volume3.replicas) == 2
    wait_for_rebuild_complete(client, volume3_name)

    # Wait for deletion of extra replica
    volume3 = wait_for_volume_replica_count(client, volume3_name, 1)
    assert volume3.replicas[0]["hostId"] == node1.name
    assert volume3.replicas[0]["mode"] == "RW"
    assert volume3.replicas[0]["running"] is True

    delete_and_wait_pod(core_api, pod3_name)
    wait_for_volume_detached(client, volume3_name)

    # Case 4: Make sure failed to schedule local replica doesn't block the
    # the creation of other replicas.

    replica_node_soft_anti_affinity_setting = \
        client.by_id_setting(SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY)
    try:
        client.update(replica_node_soft_anti_affinity_setting,
                      value="false")
    except Exception as e:
        print("Exception when update "
              "Replica Node Level Soft Anti-Affinity setting",
              replica_node_soft_anti_affinity_setting, e)

    client.update(node3, allowScheduling=False)

    volume4_name = volume_name + "-4"
    volume4_size = str(1 * Gi)

    volume4 = client.create_volume(name=volume4_name,
                                   size=volume4_size,
                                   numberOfReplicas=1,
                                   dataLocality="best-effort",
                                   dataEngine=DATA_ENGINE)

    volume4 = wait_for_volume_detached(client, volume4_name)
    volume4 = client.by_id_volume(volume4_name)

    volume4_replica_name = volume4.replicas[0]["name"]

    volume4.attach(hostId=node3.name)

    wait_for_volume_healthy(client, volume4_name)

    volume4 = client.by_id_volume(volume4_name)
    assert len(volume4.replicas) == 2

    for replica in volume4.replicas:
        if replica["name"] == volume4_replica_name:
            assert replica["running"] is True
            assert replica["mode"] == "RW"
        else:
            assert replica["running"] is False
            assert replica["mode"] == ""

    assert volume4.conditions.Scheduled.reason == \
        "LocalReplicaSchedulingFailure"

    volume4 = volume4.updateReplicaCount(replicaCount=3)

    volume4 = wait_for_volume_degraded(client, volume4_name)

    v4_node1_replica_count = 0
    v4_node2_replica_count = 0
    v4_failed_replica_count = 0

    for replica in volume4.replicas:
        if replica["hostId"] == node1.name:
            v4_node1_replica_count += 1
        elif replica["hostId"] == node2.name:
            v4_node2_replica_count += 1
        elif replica["hostId"] == "":
            v4_failed_replica_count += 1

    assert v4_node1_replica_count == 1
    assert v4_node2_replica_count == 1
    assert v4_failed_replica_count > 0

    volume4 = volume4.updateReplicaCount(replicaCount=2)

    volume4 = wait_for_volume_replica_count(client, volume4_name, 3)

    v4_node1_replica_count = 0
    v4_node2_replica_count = 0
    v4_failed_replica_count = 0

    for replica in volume4.replicas:
        if replica["hostId"] == node1.name:
            v4_node1_replica_count += 1
        elif replica["hostId"] == node2.name:
            v4_node2_replica_count += 1
        elif replica["hostId"] == "":
            v4_failed_replica_count += 1

    assert v4_node1_replica_count == 1
    assert v4_node2_replica_count == 1
    assert v4_failed_replica_count > 0

    volume4 = volume4.updateReplicaCount(replicaCount=1)

    volume4 = wait_for_volume_replica_count(client, volume4_name, 2)

    v4_node1_replica_count = 0
    v4_node2_replica_count = 0
    v4_failed_replica_count = 0

    for replica in volume4.replicas:
        if replica["hostId"] == node1.name:
            v4_node1_replica_count += 1
        elif replica["hostId"] == node2.name:
            v4_node2_replica_count += 1
        elif replica["hostId"] == "":
            v4_failed_replica_count += 1

    assert v4_node1_replica_count + v4_node2_replica_count == 1
    assert v4_failed_replica_count == 1

    volume4 = volume4.updateDataLocality(dataLocality="disabled")
    volume4 = volume4.updateReplicaCount(replicaCount=2)

    running_replica_count = 0
    for _ in range(RETRY_COUNTS):
        volume4 = client.by_id_volume(volume4_name)
        running_replica_count = 0
        for r in volume4.replicas:
            if r.failedAt == "" and r.running is True:
                running_replica_count += 1
        if running_replica_count == 2:
            break
        time.sleep(RETRY_INTERVAL)
    assert running_replica_count == 2

    v4_node1_replica_count = 0
    v4_node2_replica_count = 0
    v4_node3_replica_count = 0

    for replica in volume4.replicas:
        wait_for_replica_running(client, volume4_name, replica["name"])
        if replica["hostId"] == node1.name:
            v4_node1_replica_count += 1
        elif replica["hostId"] == node2.name:
            v4_node2_replica_count += 1
        elif replica["hostId"] == node3.name:
            v4_node3_replica_count += 1
    assert v4_node1_replica_count == 1
    assert v4_node2_replica_count == 1
    assert v4_node3_replica_count == 0


def test_replica_schedule_to_disk_with_most_usable_storage(client, volume_name, request):  # NOQA
    """
    Scenario : test replica schedule to disk with the most usable storage

    Given default disk 3/4 storage is reserved on the current node.
    And disk-1 with 1/4 of default disk space + 10 Gi.
    And add disk-1 to the current node.

    When create and attach volume.

    Then volume replica     on the current node scheduled to disk-1.
         volume replica not on the current node scheduled to default disk.
    """
    default_disk_available = 0
    self_host_id = get_self_host_id()
    cleanup_node_disks(client, self_host_id)
    node = client.by_id_node(self_host_id)
    disks = node.disks
    update_disks = get_update_disks(disks)
    for disk in update_disks.values():
        if disk.path != DEFAULT_DISK_PATH:
            continue

        default_disk_available = int(disk.storageMaximum/4)
        disk.storageReserved = disk.storageMaximum-default_disk_available
        break

    node = update_node_disks(client, node.name, disks=update_disks,
                             retry=True)
    disks = node.disks
    for name, disk in iter(disks.items()):
        wait_for_disk_status(client, node.name,
                             name, "storageReserved",
                             disk.storageMaximum-default_disk_available)

    disk_path = create_host_disk(client, 'vol-disk-1',
                                 str(10 * Gi + default_disk_available),
                                 node.name)
    disk = {"path": disk_path, "allowScheduling": True}
    update_disks = get_update_disks(disks)
    update_disks["disk1"] = disk
    node = update_node_disks(client, node.name, disks=update_disks,
                             retry=True)

    node = common.wait_for_disk_update(client, node.name,
                                       len(update_disks))
    assert len(node.disks) == len(update_disks)

    volume = create_and_check_volume(client, volume_name)
    volume.attach(hostId=get_self_host_id())
    volume = wait_for_volume_healthy(client, volume_name)

    expect_scheduled_disk = {}
    nodes = client.list_node()
    for node in nodes:
        for _, disk in iter(node.disks.items()):
            if node.name == self_host_id and disk.path != DEFAULT_DISK_PATH:
                expect_scheduled_disk[node.name] = disk
            elif node.name != self_host_id and disk.path == DEFAULT_DISK_PATH:
                expect_scheduled_disk[node.name] = disk

    volume = client.by_id_volume(volume_name)
    for replica in volume.replicas:
        hostId = replica.hostId
        assert replica.diskID == expect_scheduled_disk[hostId].diskUUID


def test_soft_anti_affinity_scheduling_volume_enable(client, volume_name): # NOQA
    """
    Test the global setting will be overwrite
    if the volume enable the Soft Anti-Affinity

    With Soft Anti-Affinity, a new replica should still be scheduled on a node
    with an existing replica, which will result in "Healthy" state but limited
    redundancy.

    Setup
    - Disable Soft Anti-Affinity in global setting

    Given
    - Create a volume with replicaSoftAntiAffinity=enabled in the spec
    - Attach to the current node and Generate and write `data` to the volume

    When
    - Disable current node's scheduling.
    - Remove the replica on the current node

    Then
    - Wait for the volume to complete rebuild. Volume should have 3 replicas.
    - Verify `data`
    """
    update_setting(client, SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "false")
    host_id = get_self_host_id()

    client.create_volume(name=volume_name,
                         size=str(1 * Gi),
                         numberOfReplicas=3,
                         backingImage="",
                         frontend=VOLUME_FRONTEND_BLOCKDEV,
                         snapshotDataIntegrity=SNAPSHOT_DATA_INTEGRITY_IGNORED,
                         replicaSoftAntiAffinity="enabled",
                         dataEngine=DATA_ENGINE)

    volume = wait_for_volume_detached(client, volume_name)
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    data = write_volume_random_data(volume)

    node = client.by_id_node(host_id)
    node = set_node_scheduling(client, node, allowScheduling=False)

    delete_replica_on_test_node(client, volume_name)
    wait_for_volume_degraded(client, volume_name)
    wait_for_volume_healthy(client, volume_name)

    check_volume_data(volume, data)


def test_soft_anti_affinity_scheduling_volume_disable(client, volume_name): # NOQA
    """
    Test the global setting will be overwrite
    if the volume disable the Soft Anti-Affinity

    With Soft Anti-Affinity disabled,
    scheduling on nodes with existing replicas should be forbidden,
    resulting in "Degraded" state.

    Setup
    - Enable Soft Anti-Affinity in global setting

    Given
    - Create a volume with replicaSoftAntiAffinity=disabled in the spec
    - Attach to the current node and Generate and write `data` to the volume

    When
    - Disable current node's scheduling.
    - Remove the replica on the current node

    Then
    - Verify volume will be in degraded state.
    - Verify volume reports condition `scheduled == false`
    - Verify only two of volume are healthy.
    - Check volume `data`
    """
    update_setting(client, SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    host_id = get_self_host_id()

    client.create_volume(name=volume_name,
                         size=str(1 * Gi),
                         numberOfReplicas=3,
                         backingImage="",
                         frontend=VOLUME_FRONTEND_BLOCKDEV,
                         snapshotDataIntegrity=SNAPSHOT_DATA_INTEGRITY_IGNORED,
                         replicaSoftAntiAffinity="disabled",
                         dataEngine=DATA_ENGINE)

    volume = wait_for_volume_detached(client, volume_name)
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)
    data = write_volume_random_data(volume)

    node = client.by_id_node(host_id)
    node = set_node_scheduling(client, node, allowScheduling=False)

    delete_replica_on_test_node(client, volume_name)
    wait_for_volume_degraded(client, volume_name)
    wait_scheduling_failure(client, volume_name)

    for _ in range(RETRY_COUNTS_SHORT):
        volume = client.by_id_volume(volume_name)
        assert volume.robustness == VOLUME_ROBUSTNESS_DEGRADED
        assert volume.conditions.Scheduled.status == "False"

        healthy_replica_count = 0
        for replica in volume.replicas:
            if replica.running is True:
                healthy_replica_count = healthy_replica_count + 1
        assert healthy_replica_count == 2

        time.sleep(RETRY_INTERVAL)

    check_volume_data(volume, data)


@pytest.mark.v2_volume_test  # NOQA
def test_data_locality_strict_local_node_affinity(client, core_api, apps_api, storage_class, statefulset, request):  # NOQA
    """
    Scenario: data-locality (strict-local) should schedule Pod to the same node

    Issue: https://github.com/longhorn/longhorn/issues/5448

    Given a StorageClass (lh-test) has dataLocality (strict-local)
    And the StorageClass (lh-test) has numberOfReplicas (1)
    And the StorageClass (lh-test) exists

    And a StatefulSet (test-1) has StorageClass (lh-test)
    And the StatefulSet (test-1) created.
    And the StatefulSet (test-1) all Pods are in state (healthy).
    And the StatefulSet (test-1) is deleted.
    And the StatefulSet (test-1) PVC exists.

    And a StatefulSet (test-2) has StorageClass (lh-test)
    And the StatefulSet (test-2) has replicas (2)
    And the StatefulSet (test-2) created.
    And the StatefulSet (test-2) all Pods is in state (healthy).

    When the StatefulSet (test-1) created.
    Then the StatefulSet (test-1) all Pods are in state (healthy).
    """

    def wait_for_statefulset_pods_healthy(statefulset):
        pod_list = get_statefulset_pod_info(core_api, statefulset)
        wait_for_pods_volume_state(
            client, pod_list,
            VOLUME_FIELD_ROBUSTNESS,
            VOLUME_ROBUSTNESS_HEALTHY,
            retry_counts=int(60 / RETRY_INTERVAL)
        )

    storage_class["parameters"]["dataLocality"] = "strict-local"
    storage_class["parameters"]["numberOfReplicas"] = "1"
    create_storage_class(storage_class)

    statefulset["metadata"]["name"] = "test-1"
    spec = statefulset['spec']
    spec['replicas'] = 1
    spec['volumeClaimTemplates'][0]['spec']['storageClassName'] = \
        storage_class['metadata']['name']
    statefulset['spec'] = spec
    create_and_wait_statefulset(statefulset)

    pod_list = get_statefulset_pod_info(core_api, statefulset)

    wait_for_statefulset_pods_healthy(statefulset)

    delete_statefulset(apps_api, statefulset)
    for sts_pod in pod_list:
        wait_delete_pod(core_api, sts_pod['pod_uid'])

    statefulset_2 = copy.deepcopy(statefulset)
    statefulset_2["metadata"]["name"] = "test-2"
    statefulset_2['spec']['replicas'] = 2
    create_and_wait_statefulset(statefulset_2)

    def finalizer():
        client = get_longhorn_api_client()
        delete_and_wait_statefulset(core_api, client, statefulset_2)
    request.addfinalizer(finalizer)

    wait_for_statefulset_pods_healthy(statefulset_2)

    create_and_wait_statefulset(statefulset)
    wait_for_statefulset_pods_healthy(statefulset)


@pytest.mark.v2_volume_test  # NOQA
def test_allow_empty_node_selector_volume_setting(client, volume_name): # NOQA
    """
    Test the global setting allow-empty-node-selector-volume

    If true, a replica of the volume without node selector
    can be scheduled on node with tags.

    If false, a replica of the volume without node selector
    can not be scheduled on node with tags.

    Setup
    - Prepare 3 nodes
    - Add `AVAIL` tag to nodes
    - Set allow-empty-node-selector-volume to `false`

    When
    - Create a Volume with 3 replicas without tag

    Then
    - All replicas can not be scheduled to the nodes

    When
    - Remove `AVAIL` tag from one of the node
    - Set allow-empty-node-selector-volume to `true`

    Then
    - Wait for a while for controller to resync the volume,
      all replicas can be scheduled to the nodes
    """
    # Setup
    node_tag = ["AVAIL"]
    for node in client.list_node():
        set_node_tags(client, node, tags=node_tag, retry=True)
        wait_for_node_tag_update(client, node.name, node_tag)

    update_setting(client, SETTING_ALLOW_EMPTY_NODE_SELECTOR_VOLUME, "false")

    # Check volume can not be scehduled
    client.create_volume(name=volume_name, size=SIZE,
                         dataEngine=DATA_ENGINE)
    volume = wait_for_volume_detached(client, volume_name)

    volume = client.by_id_volume(volume.name)
    volume = wait_for_volume_condition_scheduled(client, volume_name,
                                                 "status",
                                                 CONDITION_STATUS_FALSE)

    # Rremove tag from 1 node and set setting allow-empty-node-selector-volume
    # to true
    node = client.by_id_node(get_self_host_id())
    set_node_tags(client, node, tags=[], retry=True)
    update_setting(client, SETTING_ALLOW_EMPTY_NODE_SELECTOR_VOLUME, "true")

    # Volume can be schedule
    volume = wait_for_volume_condition_scheduled(client, volume_name, "status",
                                                 CONDITION_STATUS_TRUE)
    assert volume.ready

    # All replicas schedule to nodes
    volume.attach(hostId=get_self_host_id())
    volume = wait_for_volume_healthy(client, volume_name)


def prepare_for_affinity_tests(client, volume_name, request): # NOQA
    """
    For 'test_global_disk_soft_anti_affinity' and
    'test_volume_disk_soft_anti_affinity' use, they have identical
    the same preparation steps as below:

    Given
    - One node has three disks
    - The three disks have very different sizes
    - Only two disks are available for scheduling
    - No other node is available for scheduling
    """
    def finalizer():
        volume = client.by_id_volume(volume_name)
        volume.detach(hostId=lht_hostId)
        wait_for_volume_detached(client, volume_name)
        client.delete(volume)
        wait_for_volume_delete(client, volume.name)
        cleanup_host_disks(client, 'vol-disk-1', 'vol-disk-2')
    request.addfinalizer(finalizer)

    # Preparation
    lht_hostId = get_self_host_id()
    node = client.by_id_node(lht_hostId)
    disks = node.disks
    disk_path1 = create_host_disk(client, 'vol-disk-1',
                                  str(2 * Gi), lht_hostId)
    disk1 = {"path": disk_path1, "allowScheduling": True}
    disk_path2 = create_host_disk(client, 'vol-disk-2',
                                  str(4 * Gi), lht_hostId)
    disk2 = {"path": disk_path2, "allowScheduling": False}

    update_disk = get_update_disks(disks)
    update_disk["disk1"] = disk1
    update_disk["disk2"] = disk2

    node = update_node_disks(client, node.name, disks=update_disk, retry=True)
    node = wait_for_disk_update(client, lht_hostId, len(update_disk))
    assert len(node.disks) == len(update_disk)

    # Make only current node schedulable
    nodes = client.list_node()
    for node in nodes:
        if node.id != lht_hostId:
            set_node_scheduling(client, node, allowScheduling=False)

    return disk_path1, disk_path2



def test_global_disk_soft_anti_affinity(client, volume_name, request): # NOQA
    """
    1. When Replica Disk Soft Anti-Affinity is false, it should be impossible
       to schedule replicas to the same disk.
    2. When Replica Disk Soft Anti-Affinity is true, it should be possible to
       schedule replicas to the same disk.
    3. Whether or not Replica Disk Soft Anti-Affinity is true or false, the
       scheduler should prioritize scheduling replicas to different disks.

    Given
    - One node has three disks
    - The three disks have very different sizes
    - Only two disks are available for scheduling
    - No other node is available for scheduling

    When
    - Global Replica Node Level Soft Anti-Affinity is true
    - Global Replica Zone Level Soft Anti-Affinity is true
    - Global Replica Disk Level Soft Anti-Affinity is false
    - Create a volume with three replicas and a size such that all replicas
      could fit on the largest disk and still leave it with the most available
      space
    - Attach the volume to the schedulable node

    Then
    - Verify the volume is in a degraded state
    - Verify only two of the three replicas are healthy
    - Verify the remaining replica doesn't have a spec.nodeID

    When
    - Change the global Replica Disk Level Soft Anti-Affinity to true

    Then
    - Verify the volume is in a healthy state
    - Verify all three replicas are healthy (two replicas have the same
      spec.diskID)

    When
    - Enable scheduling on the third disk
    - Delete one of the two replicas with the same spec.diskID

    Then
    - Verify the volume is in a healthy state
    - Verify all three replicas are healthy
    - Verify all three replicas have a different spec.diskID
    """
    # Preparation
    disk_path1, disk_path2 = prepare_for_affinity_tests(client,
                                                        volume_name,
                                                        request)

    # Test start
    update_setting(client, SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    update_setting(client, SETTING_REPLICA_ZONE_SOFT_ANTI_AFFINITY, "true")
    update_setting(client, SETTING_REPLICA_DISK_SOFT_ANTI_AFFINITY, "false")

    lht_hostId = get_self_host_id()
    client.create_volume(name=volume_name, size=str(500*Mi),
                         dataEngine=DATA_ENGINE)
    volume = wait_for_volume_detached(client, volume_name)
    volume.attach(hostId=lht_hostId)
    volume = wait_for_volume_degraded(client, volume_name)

    num_running = 0
    for replica in volume.replicas:
        if replica.running:
            num_running += 1
        else:
            assert replica.hostId == ""

    assert num_running == 2

    # After enable SETTING_REPLICA_DISK_SOFT_ANTI_AFFINITY to true,
    # replicas can schedule on the same disk, therefore volume become healthy
    update_setting(client, SETTING_REPLICA_DISK_SOFT_ANTI_AFFINITY, "true")

    volume = wait_for_volume_healthy(client, volume_name)

    node = client.by_id_node(lht_hostId)
    disks = node.disks
    for fsid, disk in iter(disks.items()):
        if disk.path == disk_path2:
            disk.allowScheduling = True

    # Enable disk2
    update_disks = get_update_disks(disks)
    update_node_disks(client, node.name, disks=update_disks, retry=True)

    # Delete one of the two replicas with the same diskID
    disk_id = []
    for replica in volume.replicas:
        if replica.diskID not in disk_id:
            disk_id.append(replica.diskID)
        else:
            volume.replicaRemove(name=replica.name)

    volume = wait_for_volume_degraded(client, volume_name)
    volume = wait_for_volume_healthy(client, volume_name)

    # Replcas should located on 3 different disks on current node
    disk_id.clear()
    for replica in volume.replicas:
        assert replica.diskID not in disk_id
        disk_id.append(replica.diskID)

@pytest.mark.v2_volume_test  # NOQA
def test_allow_empty_disk_selector_volume_setting(client, volume_name): # NOQA
    """
    Test the global setting allow-empty-disk-selector-volume

    If true, a replica of the volume without disk selector
    can be scheduled on disk with tags.

    If false, a replica of the volume without disk selector
    can not be scheduled on disk with tags.

    Setup
    - Prepare 3 nodes each with one disk
    - Add `AVAIL` tag to every disk
    - Set allow-empty-disk-selector-volume to `false`

    When
    - Create a Volume with 3 replicas without tag

    Then
    - All replicas can not be scheduled to the disks on the nodes

    When
    - Remove `AVAIL` tag from one of the node
    - Set allow-empty-disk-selector-volume to `true`

    Then
    - Wait for a while for controller to resync the volume,
      all replicas can be scheduled to the disks on the nodes
    """
    # Preparation
    nodes = client.list_node()
    for node in nodes:
        disks = get_update_disks(node.disks)
        disks[list(disks)[0]].tags = ["AVAIL"]
        update_node_disks(client, node.name, disks=disks)

    update_setting(client, SETTING_ALLOW_EMPTY_DISK_SELECTOR_VOLUME, "false")

    # Check volume can not be scehduled
    client.create_volume(name=volume_name, size=SIZE,
                         dataEngine=DATA_ENGINE)
    volume = wait_for_volume_detached(client, volume_name)

    volume = client.by_id_volume(volume.name)
    volume = wait_for_volume_condition_scheduled(client, volume_name,
                                                 "status",
                                                 CONDITION_STATUS_FALSE)

    # Remove tag from current node
    host_id = get_self_host_id()
    node = client.by_id_node(host_id)
    disks = get_update_disks(node.disks)
    disks[list(disks)[0]].tags = []
    update_node_disks(client, node.name, disks=disks)
    update_setting(client, SETTING_ALLOW_EMPTY_DISK_SELECTOR_VOLUME, "true")

    # Volume can be schedule
    volume = wait_for_volume_condition_scheduled(client, volume_name, "status",
                                                 CONDITION_STATUS_TRUE)
    assert volume.ready

    # All replicas schedule to disks on nodes
    volume.attach(hostId=host_id)
    volume = wait_for_volume_healthy(client, volume_name)


def test_volume_disk_soft_anti_affinity(client, volume_name, request): # NOQA
    """
    1. When Replica Disk Soft Anti-Affinity is disabled, it should be
       impossible to schedule replicas to the same disk.
    2. When Replica Disk Soft Anti-Affinity is enabled, it should be possible
       to schedule replicas to the same disk.
    3. Whether or not Replica Disk Soft Anti-Affinity is enabled or disabled,
       the scheduler should prioritize scheduling replicas to different disks.

    Given
    - One node has three disks
    - The three disks have very different sizes
    - Only two disks are available for scheduling
    - No other node is available for scheduling

    When
    - Global Replica Node Level Soft Anti-Affinity is true
    - Global Replica Zone Level Soft Anti-Affinity is true
    - Create a volume with three replicas, a size such that all replicas could
      fit on the largest disk and still leave it with the most available space,
      and spec.replicaDiskSoftAntiAffinity = disabled
    - Attach the volume to the schedulable node

    Then
    - Verify the volume is in a degraded state
    - Verify only two of the three replicas are healthy
    - Verify the remaining replica doesn't have a spec.nodeID

    When
    - Change the volume's spec.replicaDiskSoftAntiAffinity to enabled

    Then
    - Verify the volume is in a healthy state
    - Verify all three replicas are healthy (two replicas have the same
      spec.diskID)

    When
    - Enable scheduling on the third disk
    - Delete one of the two replicas with the same spec.diskID

    Then
    - Verify the volume is in a healthy state
    - Verify all three replicas are healthy
    - Verify all three replicas have a different diskID
    """
    # Preparation
    disk_path1, disk_path2 = prepare_for_affinity_tests(client,
                                                        volume_name,
                                                        request)

    # Test start
    update_setting(client, SETTING_REPLICA_NODE_SOFT_ANTI_AFFINITY, "true")
    update_setting(client, SETTING_REPLICA_ZONE_SOFT_ANTI_AFFINITY, "true")

    lht_hostId = get_self_host_id()
    client.create_volume(name=volume_name, size=str(500*Mi),
                         replicaDiskSoftAntiAffinity="disabled",
                         dataEngine=DATA_ENGINE)
    volume = wait_for_volume_detached(client, volume_name)
    assert volume.replicaDiskSoftAntiAffinity == "disabled"

    volume.attach(hostId=lht_hostId)
    volume = wait_for_volume_degraded(client, volume_name)

    num_running = 0
    for replica in volume.replicas:
        if replica.running:
            num_running += 1
        else:
            assert replica.hostId == ""

    assert num_running == 2

    # After set update volume.updateReplicaDiskSoftAntiAffinity to enabled,
    # replicas can schedule on the same disk, therefore volume become healthy
    volume = volume.updateReplicaDiskSoftAntiAffinity(
             replicaDiskSoftAntiAffinity="enabled")
    assert volume.replicaDiskSoftAntiAffinity == "enabled"

    volume = wait_for_volume_healthy(client, volume_name)

    disk_id = []
    for replica in volume.replicas:
        if replica.diskID not in disk_id:
            disk_id.append(replica.diskID)

    assert len(disk_id) == 2

    node = client.by_id_node(lht_hostId)
    disks = node.disks
    for fsid, disk in iter(disks.items()):
        if disk.path == disk_path2:
            disk.allowScheduling = True

    # Enable disk2
    update_disks = get_update_disks(disks)
    update_node_disks(client, node.name, disks=update_disks, retry=True)

    # Delete one of the two replicas with the same diskID
    disk_id.clear()
    for replica in volume.replicas:
        if replica.diskID not in disk_id:
            disk_id.append(replica.diskID)
        else:
            volume.replicaRemove(name=replica.name)

    volume = wait_for_volume_degraded(client, volume_name)
    volume = wait_for_volume_healthy(client, volume_name)

    # Replcas should located on 3 different disks on current node
    disk_id.clear()
    for replica in volume.replicas:
        assert replica.diskID not in disk_id
        disk_id.append(replica.diskID)

def test_best_effort_data_locality(client, volume_name):  # NOQA
    """
    Scenario: replica should be scheduled only after volume is attached,
              and it should be scheduled to the local node.
            - volume data locality is set to `best-effort`
            - volume has 1 replica

    Issue: https://github.com/longhorn/longhorn/issues/11007
    """
    # Repeat test for 10 times to make sure replica
    # is scheduled to the local node.
    for i in range(10):
        best_effort_data_locality_test(client, f'{volume_name}-{i}')


def best_effort_data_locality_test(client, volume_name):  # NOQA
    number_of_replicas = 1
    volume = client.create_volume(name=volume_name,
                                  size=str(1 * Gi),
                                  numberOfReplicas=number_of_replicas,
                                  dataLocality="best-effort")

    # replica should stay unscheduled until volume is attached
    for _ in range(10):
        time.sleep(RETRY_INTERVAL)
        volume = client.by_id_volume(volume_name)
        assert len(volume.replicas) == number_of_replicas
        assert volume.replicas[0]['hostId'] == ""
        assert not volume.replicas[0].running

    self_node = get_self_host_id()
    # attach volume to the self_node
    volume.attach(hostId=self_node)
    volume = wait_for_volume_healthy(client, volume_name)
    # wait for replica to be on the self_node
    for _ in range(30):
        volume = client.by_id_volume(volume_name)
        assert len(volume.replicas) == number_of_replicas
        # fail if replica is scheduled to another node
        assert (volume.replicas[0]['hostId'] == "" or
                volume.replicas[0]['hostId'] == self_node)
        if volume.replicas[0]['hostId'] == self_node:
            break
        time.sleep(RETRY_INTERVAL)

    assert volume.replicas[0]['hostId'] == self_node
