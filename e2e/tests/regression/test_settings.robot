*** Settings ***
Documentation    Settings Test Cases

Test Tags    regression

Resource    ../keywords/variables.resource
Resource    ../keywords/common.resource
Resource    ../keywords/volume.resource
Resource    ../keywords/setting.resource
Resource    ../keywords/deployment.resource
Resource    ../keywords/persistentvolumeclaim.resource
Resource    ../keywords/workload.resource
Resource    ../keywords/longhorn.resource
Resource    ../keywords/backupstore.resource
Resource    ../keywords/sharemanager.resource
Resource    ../keywords/storageclass.resource
Resource    ../keywords/workload.resource
Resource    ../keywords/engine_image.resource

Test Setup    Set up test environment
Test Teardown    Cleanup test resources

*** Keywords ***
Restore engine image liveness probe default settings
    # TODO: move to setting.resource
    Setting engine-image-pod-liveness-probe-timeout is set to 4
    Setting engine-image-pod-liveness-probe-period is set to 5
    Setting engine-image-pod-liveness-probe-failure-threshold is set to 3
    Wait for engine image DaemonSet rollout to complete
    Cleanup test resources

Wait for engine image DaemonSet rollout to complete
    # TODO: move to engine_image.resource
    Run command and wait for output
    ...    kubectl -n longhorn-system rollout status ds -l longhorn.io/component=engine-image --timeout=180s
    ...    successfully rolled out

Multiple engine image DaemonSets exist
    # TODO: move to engine_image.resource
    ${result}=    Run Command And Get Output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image --no-headers | wc -l
    Should Be True    ${result} > 1    msg=Expected more than one engine-image DaemonSet but found ${result}

All engine image DaemonSets have liveness probe timeout ${timeout} period ${period} failure threshold ${failure_threshold}
    # TODO: move to engine_image.resource
    ${count}=    Run Command And Get Output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image --no-headers | wc -l
    ${count}=    Convert To Integer    ${count}
    FOR    ${index}    IN RANGE    ${count}
        Run command and wait for output
        ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[${index}].spec.template.spec.containers[0].livenessProbe.timeoutSeconds}'
        ...    ${timeout}
        Run command and wait for output
        ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[${index}].spec.template.spec.containers[0].livenessProbe.periodSeconds}'
        ...    ${period}
        Run command and wait for output
        ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[${index}].spec.template.spec.containers[0].livenessProbe.failureThreshold}'
        ...    ${failure_threshold}
    END

*** Test Cases ***
Test Setting Update With Valid Value
    [Tags]    setting
    [Documentation]    Test that valid setting updates are applied correctly.
    [Template]    Update Setting To Valid Value And Verify
    default-replica-count    1    {"v1":"1","v2":"1"}
    default-replica-count    {"v1":"5","v2":"10"}    {"v1":"5","v2":"10"}
    disable-revision-counter    {"v1":"false"}    {"v1":"false"}

Test Setting Update With Invalid Value
    [Tags]    setting
    [Documentation]    Test that invalid setting updates are rejected and values remain unchanged.
    [Template]    Update Setting To Invalid Value And Verify
    disable-revision-counter    {"v1":"true","v2":"true"}
    disable-revision-counter    {"v2":"true"}
    disable-revision-counter    {"v3":"true"}
    default-replica-count    {}

Test Setting Concurrent Rebuild Limit
    [Tags]    setting
    [Documentation]    Test if setting Concurrent Replica Rebuild Per Node Limit works correctly.
    Given Setting concurrent-replica-rebuild-per-node-limit is set to 1

    When Create volume 0 with    size=5Gi    numberOfReplicas=3    dataEngine=${DATA_ENGINE}
    And Attach volume 0
    And Wait for volume 0 healthy
    And Create volume 1 with    size=5Gi    numberOfReplicas=3    dataEngine=${DATA_ENGINE}
    And Attach volume 1
    And Wait for volume 1 healthy

    # Write a large amount of data into both volumes, so the rebuilding will take a while.
    And Write 4 GB data to volume 0
    And Write 4 GB data to volume 1

    # Delete replica of volume 1 and replica on the same node of volume 2 to trigger (concurrent) rebuilding.
    And Delete volume 0 replica on replica node
    And Delete volume 1 replica on replica node
    Then Only one replica rebuilding on replica node will start at a time, either for volume 0 or volume 1
    And Wait until volume 0 replica rebuilding completed on replica node
    And Wait until volume 1 replica rebuilding completed on replica node

    Given Setting concurrent-replica-rebuild-per-node-limit is set to 2
    When Delete volume 0 replica on replica node
    And Delete volume 1 replica on replica node
    Then Both volume 0 and volume 1 replica rebuilding on replica node will start at the same time
    And Wait until volume 0 replica rebuilding completed on replica node
    And Wait until volume 1 replica rebuilding completed on replica node

    Given Setting concurrent-replica-rebuild-per-node-limit is set to 1
    When Delete volume 0 replica on replica node
    And Wait until volume 0 replica rebuilding started on replica node
    And Delete volume 1 replica on replica node
    And Delete volume 0 replica on replica node
    And Wait until volume 0 replica rebuilding stopped on replica node
    Then Only one replica rebuilding on replica node will start at a time, either for volume 0 or volume 1
    And Wait until volume 0 replica rebuilding completed on replica node
    And Wait until volume 1 replica rebuilding completed on replica node

    # Test the setting won't intervene normal attachment.
    Given Setting concurrent-replica-rebuild-per-node-limit is set to 1
    When Detach volume 1
    And Wait for volume 1 detached
    And Delete volume 0 replica on replica node
    And Wait until volume 0 replica rebuilding started on replica node
    And Attach volume 1
    And Wait for volume 1 healthy
    And Wait until volume 0 replica rebuilding completed on replica node
    And Wait for volume 0 healthy
    Then Check volume 0 data is intact
    And Check volume 1 data is intact

Test Setting Network For RWX Volume Endpoint
    [Tags]    setting    volume    rwx    storage-network    sharemanager
    [Documentation]    Test if setting endpoint-network-for-rwx-volume works correctly.
    ...
    ...                Issues:
    ...                    - https://github.com/longhorn/longhorn/issues/10269
    ...                    - https://github.com/longhorn/longhorn/issues/8184
    ...
    ...                Precondition: NAD network configured.

    Given Setting endpoint-network-for-rwx-volume is set to ${EMPTY}
    And Create storageclass longhorn-test with    dataEngine=${DATA_ENGINE}    numberOfReplicas=3
    When Create persistentvolumeclaim 0    volume_type=RWX    sc_name=longhorn-test
    And Create deployment 0 with persistentvolumeclaim 0 with max replicaset
    Then Check Longhorn workload pods not running with CNI interface lhnet2
        ...    longhorn-csi-plugin
        ...    longhorn-share-manager
    And Check sharemanager not using headless service

    And Delete deployment 0
    And Delete persistentvolumeclaim 0
    And Wait for all sharemanager to be deleted

    When Setting endpoint-network-for-rwx-volume is set to kube-system/demo-172-16-0-0
    And Create persistentvolumeclaim 1    volume_type=RWX    sc_name=longhorn-test
    And Create deployment 1 with persistentvolumeclaim 1 with max replicaset
    Then Check Longhorn workload pods is running with CNI interface lhnet2
        ...    longhorn-csi-plugin
        ...    longhorn-share-manager
    And Check sharemanager is using headless service

Test Setting Csi Components Resource Limits
    [Documentation]    Issue: https://github.com/longhorn/longhorn/issues/12224
    When Setting system-managed-csi-components-resource-limits is set to {"csi-attacher":{"requests":{"cpu":"100m","memory":"128Mi"},"limits":{"cpu":"200m","memory":"256Mi"}},"node-driver-registrar":{"requests":{"cpu":"100m","memory":"128Mi"},"limits":{"cpu":"200m","memory":"256Mi"}},"longhorn-csi-plugin":{"requests":{"cpu":"150m","memory":"128Mi"},"limits":{"cpu":"250m","memory":"256Mi"}}}
    And Wait for Longhorn components all running
    Then Run command and wait for output
    ...    kubectl get pod -l app=csi-attacher -o jsonpath='{.items[0].spec.containers[*].resources.requests}' -n longhorn-system
    ...    {"cpu":"100m","memory":"128Mi"}
    And Run command and wait for output
    ...    kubectl get pod -l app=csi-attacher -o jsonpath='{.items[0].spec.containers[*].resources.limits}' -n longhorn-system
    ...    {"cpu":"200m","memory":"256Mi"}
    And Run command and wait for output
    ...    kubectl get pod -l app=longhorn-csi-plugin -o jsonpath='{.items[0].spec.containers[0].resources.requests}' -n longhorn-system
    ...    {"cpu":"100m","memory":"128Mi"}
    And Run command and wait for output
    ...    kubectl get pod -l app=longhorn-csi-plugin -o jsonpath='{.items[0].spec.containers[0].resources.limits}' -n longhorn-system
    ...    {"cpu":"200m","memory":"256Mi"}
    And Run command and wait for output
    ...    kubectl get pod -l app=longhorn-csi-plugin -o jsonpath='{.items[0].spec.containers[2].resources.requests}' -n longhorn-system
    ...    {"cpu":"150m","memory":"128Mi"}
    And Run command and wait for output
    ...    kubectl get pod -l app=longhorn-csi-plugin -o jsonpath='{.items[0].spec.containers[2].resources.limits}' -n longhorn-system
    ...    {"cpu":"250m","memory":"256Mi"}

Test Setting Blacklist For Auto Delete Pod
    [Tags]    setting
    [Documentation]    Test if setting blacklist-for-auto-delete-pod-when-volume-detached-unexpectedly works correctly.
    ...                Issues:
    ...                    - https://github.com/longhorn/longhorn/issues/12120
    ...                    - https://github.com/longhorn/longhorn/issues/12121
    IF    '${DATA_ENGINE}' == 'v2'
        Skip    Test case not support for v2 data engine
    END

    Given Setting blacklist-for-auto-delete-pod-when-volume-detached-unexpectedly is set to apps/ReplicaSet;apps/DaemonSet
    When Create storageclass longhorn-test with    dataEngine=${DATA_ENGINE}
    And Create persistentvolumeclaim 0    volume_type=RWO    sc_name=longhorn-test
    And Create deployment 0 with persistentvolumeclaim 0 and liveness probe

    When Kill volume engine process for deployment 0
    And Wait for deployment 0 pod stuck in CrashLoopBackOff

    When Setting blacklist-for-auto-delete-pod-when-volume-detached-unexpectedly is set to apps/DaemonSet
    And Wait for deployment 0 pods stable

Test Default Settings Quoting
    [Tags]    setting    uninstall
    [Documentation]    Verify that Longhorn correctly handles quoted and unquoted values in default
    ...                settings during installation, for both helm and manifest install methods.
    ...
    ...                Issue: https://github.com/longhorn/longhorn/issues/11854
    ...
    ...                Test steps:
    ...                1. Uninstall Longhorn.
    ...                2. If install method is helm, patch values.yaml with:
    ...                       defaultSettings.defaultReplicaCount: '{"v1":"4","v2":"2"}' (with quotes)
    ...                       defaultSettings.deletingConfirmationFlag: true (no quotes)
    ...                   If install method is manifest, append to default-setting.yaml section of
    ...                   longhorn.yaml:
    ...                       default-replica-count: '{"v1":"4","v2":"2"}'
    ...                       deleting-confirmation-flag: true
    ...                   then install Longhorn.
    ...                3. Wait for Longhorn to be running.
    ...                4. Check that default-replica-count is {"v1":"4","v2":"2"} and
    ...                   deleting-confirmation-flag is true.

    Given Setting deleting-confirmation-flag is set to true
    And Uninstall Longhorn
    And Check all Longhorn CRD removed

    ${LONGHORN_INSTALL_METHOD} =    Get Environment Variable    LONGHORN_INSTALL_METHOD    default=manifest
    IF    '${LONGHORN_INSTALL_METHOD}' == 'helm'
        # Patch values.yaml: defaultReplicaCount with a quoted JSON string, deletingConfirmationFlag without quotes.
        # The custom_cmd outputs a values.yaml file used by helm install via -f values.yaml.
        ${patch} =    Set Variable
        ...    .defaultSettings.defaultReplicaCount = "{\\"v1\\":\\"4\\",\\"v2\\":\\"2\\"}" | .defaultSettings.deletingConfirmationFlag = true
        ${helm_cmd} =    Set Variable    yq eval \'${patch}\' ${LONGHORN_REPO_DIR}/chart/values.yaml > values.yaml
        Install Longhorn    custom_cmd=${helm_cmd}
    ELSE
        # Append two settings lines after the "default-setting.yaml" key in the longhorn.yaml ConfigMap,
        # using sed append. Second sed inserts default-replica-count first so it appears before
        # deleting-confirmation-flag in the block (sed /pattern/a inserts immediately after the match).
        ${manifest_cmd} =    Set Variable
        ...    sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}deleting-confirmation-flag: true" longhorn.yaml && sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}default-replica-count: '{\\"v1\\":\\"4\\",\\"v2\\":\\"2\\"}'" longhorn.yaml
        Install Longhorn    custom_cmd=${manifest_cmd}
    END

    Then Wait for longhorn ready
    And Setting default-replica-count should be {"v1":"4","v2":"2"}
    And Setting deleting-confirmation-flag should be true

Test Engine Image Liveness Probe Default Values
    [Tags]    setting    engine-image
    [Documentation]    Verify engine-image liveness probe settings exist with correct default values.
    ...                Issue: https://github.com/longhorn/longhorn/issues/12846
    When Setting engine-image-pod-liveness-probe-timeout should be 4
    And Setting engine-image-pod-liveness-probe-period should be 5
    And Setting engine-image-pod-liveness-probe-failure-threshold should be 3
    Then Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.timeoutSeconds}'
    ...    4
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.periodSeconds}'
    ...    5
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.failureThreshold}'
    ...    3

Test Engine Image Liveness Probe DaemonSet Auto Update
    [Tags]    setting    engine-image
    [Documentation]    Verify DaemonSet liveness probe values are updated after patching settings.
    ...                Issue: https://github.com/longhorn/longhorn/issues/12846
    When Setting engine-image-pod-liveness-probe-timeout is set to 15
    And Setting engine-image-pod-liveness-probe-period is set to 30
    And Setting engine-image-pod-liveness-probe-failure-threshold is set to 10
    And Wait for engine image DaemonSet rollout to complete
    Then Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.timeoutSeconds}'
    ...    15
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.periodSeconds}'
    ...    30
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.failureThreshold}'
    ...    10
    And Run command and expect output
    ...    kubectl -n longhorn-system get pod -l longhorn.io/component=engine-image -o jsonpath='{range .items[*]}{.status.containerStatuses[0].restartCount}{"\n"}{end}'
    ...    0
    [Teardown]    Restore engine image liveness probe default settings

Test Engine Image Liveness Probe Invalid Value Rejection
    [Tags]    setting    engine-image
    [Documentation]    Verify that invalid values for liveness probe settings are rejected.
    ...                Issue: https://github.com/longhorn/longhorn/issues/12846
    When Set setting engine-image-pod-liveness-probe-period to -1 will fail
    And Set setting engine-image-pod-liveness-probe-timeout to 0 will fail
    And Set setting engine-image-pod-liveness-probe-failure-threshold to abc will fail
    Then Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.timeoutSeconds}'
    ...    4
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.periodSeconds}'
    ...    5
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o jsonpath='{.items[0].spec.template.spec.containers[0].livenessProbe.failureThreshold}'
    ...    3

Test Engine Image Liveness Probe Multiple Engine Images
    [Tags]    setting    engine-image
    [Documentation]    Verify all engine-image DaemonSets are updated consistently when probe settings change.
    ...                Issue: https://github.com/longhorn/longhorn/issues/12846
    Given Create compatible engine image
    When Setting engine-image-pod-liveness-probe-timeout is set to 15
    And Setting engine-image-pod-liveness-probe-period is set to 30
    And Setting engine-image-pod-liveness-probe-failure-threshold is set to 10
    And Wait for engine image DaemonSet rollout to complete
    Then All engine image DaemonSets have liveness probe timeout 15 period 30 failure threshold 10
    [Teardown]    Restore engine image liveness probe default settings

Test Engine Image Liveness Probe Install With Custom Values
    [Tags]    setting    engine-image    uninstall
    [Documentation]    - Verify that engine-image liveness probe settings can be configured
    ...                  via Helm chart defaultSettings or manifest default-setting.yaml at install time.
    ...                - Issue: https://github.com/longhorn/longhorn/issues/12846
    ...                - Test steps:
    ...                - 1. Uninstall Longhorn and verify all CRDs removed.
    ...                - 2. Install Longhorn with custom probe values (timeout=15, period=30, failureThreshold=10).
    ...                  For helm: set via defaultSettings.engineImagePodLivenessProbeTimeout/Period/FailureThreshold.
    ...                  For manifest: append to default-setting.yaml in longhorn.yaml ConfigMap.
    ...                - 3. Wait for Longhorn ready.
    ...                - 4. Assert setting values = 15, 30, 10.
    ...                - 5. Assert DaemonSet liveness probe values = 15, 30, 10.

    Given Setting deleting-confirmation-flag is set to true
    And Uninstall Longhorn
    And Check all Longhorn CRD removed

    ${LONGHORN_INSTALL_METHOD} =    Get Environment Variable    LONGHORN_INSTALL_METHOD    default=manifest
    IF    '${LONGHORN_INSTALL_METHOD}' == 'helm'
        ${patch} =    Set Variable
        ...    .defaultSettings.engineImagePodLivenessProbeTimeout = 15 | .defaultSettings.engineImagePodLivenessProbePeriod = 30 | .defaultSettings.engineImagePodLivenessProbeFailureThreshold = 10
        ${helm_cmd} =    Set Variable    yq eval '${patch}' ${LONGHORN_REPO_DIR}/chart/values.yaml > values.yaml
        Install Longhorn    custom_cmd=${helm_cmd}
    ELSE
        ${manifest_cmd} =    Set Variable
        ...    sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-failure-threshold: 10" longhorn.yaml && sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-period: 30" longhorn.yaml && sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-timeout: 15" longhorn.yaml
        Install Longhorn    custom_cmd=${manifest_cmd}
    END

    Then Wait for longhorn ready
    And Setting engine-image-pod-liveness-probe-timeout should be 15
    And Setting engine-image-pod-liveness-probe-period should be 30
    And Setting engine-image-pod-liveness-probe-failure-threshold should be 10
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.timeoutSeconds'
    ...    15
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.periodSeconds'
    ...    30
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.failureThreshold'
    ...    10
    [Teardown]    Restore engine image liveness probe default settings

Test Engine Image Liveness Probe Upgrade With Custom Values
    [Tags]    setting    engine-image    uninstall
    [Documentation]    - Verify that engine-image liveness probe settings can be configured
    ...                  via Helm chart defaultSettings or manifest default-setting.yaml at upgrade time.
    ...                - Issue: https://github.com/longhorn/longhorn/issues/12846
    ...                - Test steps:
    ...                - 1. Uninstall Longhorn and install stable version (without liveness probe settings).
    ...                - 2. Upgrade Longhorn with custom probe values (timeout=15, period=30, failureThreshold=10).
    ...                  For helm: set via defaultSettings.engineImagePodLivenessProbeTimeout/Period/FailureThreshold.
    ...                  For manifest: append to default-setting.yaml in longhorn.yaml ConfigMap.
    ...                - 3. Wait for Longhorn ready.
    ...                - 4. Assert setting values = 15, 30, 10.
    ...                - 5. Assert DaemonSet liveness probe values = 15, 30, 10.

    ${LONGHORN_STABLE_VERSION}=    Get Environment Variable    LONGHORN_STABLE_VERSION    default=''
    IF    '${LONGHORN_STABLE_VERSION}' == ''
        Skip    LONGHORN_STABLE_VERSION not set - required for upgrade test
    END

    # Precondition: Set up environment and install Longhorn
    Given Setting deleting-confirmation-flag is set to true
    And Uninstall Longhorn
    And Check Longhorn CRD removed

    When Install Longhorn stable version
    And Set default backupstore
    And Enable v2 data engine and add block disks

    ${LONGHORN_INSTALL_METHOD} =    Get Environment Variable    LONGHORN_INSTALL_METHOD    default=manifest
    IF    '${LONGHORN_INSTALL_METHOD}' == 'helm'
        ${patch} =    Set Variable
        ...    .defaultSettings.engineImagePodLivenessProbeTimeout = 15 | .defaultSettings.engineImagePodLivenessProbePeriod = 30 | .defaultSettings.engineImagePodLivenessProbeFailureThreshold = 10
        ${helm_cmd} =    Set Variable    yq eval '${patch}' ${LONGHORN_REPO_DIR}/chart/values.yaml > values.yaml
        Upgrade Longhorn to custom version    custom_cmd=${helm_cmd}
    ELSE
        ${manifest_cmd} =    Set Variable
        ...    sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-failure-threshold: 10" longhorn.yaml && sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-period: 30" longhorn.yaml && sed -i "/default-setting\\.yaml: |-/a\\${SPACE * 4}engine-image-pod-liveness-probe-timeout: 15" longhorn.yaml
        Upgrade Longhorn to custom version    custom_cmd=${manifest_cmd}
    END

    Then Wait for longhorn ready
    And Setting engine-image-pod-liveness-probe-timeout should be 15
    And Setting engine-image-pod-liveness-probe-period should be 30
    And Setting engine-image-pod-liveness-probe-failure-threshold should be 10
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.timeoutSeconds'
    ...    15
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.periodSeconds'
    ...    30
    And Run command and expect output
    ...    kubectl -n longhorn-system get ds -l longhorn.io/component=engine-image -o json | jq '.items[0].spec.template.spec.containers[0].livenessProbe.failureThreshold'
    ...    10
    [Teardown]    Restore engine image liveness probe default settings

