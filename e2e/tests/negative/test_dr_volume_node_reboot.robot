*** Settings ***
Documentation    Test backup listing
...              https://longhorn.github.io/longhorn-tests/manual/pre-release/node-not-ready/node-restart/dr-volume-node-rebooted/

Test Tags    manual

Resource    ../keywords/common.resource
Resource    ../keywords/deployment.resource
Resource    ../keywords/workload.resource
Resource    ../keywords/longhorn.resource
Resource    ../keywords/host.resource
Resource    ../keywords/storageclass.resource
Resource    ../keywords/persistentvolumeclaim.resource
Resource    ../keywords/recurringjob.resource
Resource    ../keywords/statefulset.resource
Resource    ../keywords/volume.resource
Resource    ../keywords/snapshot.resource
Resource    ../keywords/backup.resource


Test Setup    Set test environment
Test Teardown    Cleanup test resources

*** Variables ***
${RETRY_COUNT}    400
${RETRY_INTERVAL}    1
${DATA_ENGINE}    v1

*** Test Cases ***
DR Volume Node Reboot During Initial Restoration 1
    [Tags]  manual  longhorn-8425
    [Documentation]    Test DR volume node reboot
    ...                During Initial Restoration
    Given Create volume 0 with    dataEngine=${DATA_ENGINE}
    And Attach volume 0
    And Wait for volume 0 healthy
    And Write data 0 to volume 0
    Then Volume 0 backup 0 should be able to create
    Then Create DR volume 1 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 1 restoration from backup 0 start
    Then Reboot volume 1 volume node
    And Wait for volume 1 restoration from backup 0 completed
    When Activate DR volume 1
    And Attach volume 1
    And Wait for volume 1 healthy
    Then Check volume 1 data is backup 0

DR Volume Node Reboot During Initial Restoration 2
    [Tags]  manual  longhorn-8425
    [Documentation]    Test DR volume node reboot
    ...                During Initial Restoration
    Given Create volume 02 with    dataEngine=${DATA_ENGINE}
    And Attach volume 02
    And Wait for volume 02 healthy
    And Write data 0 to volume 02
    Then Volume 02 backup 0 should be able to create
    Then Create DR volume 12 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 12 restoration from backup 0 start
    Then Reboot volume 12 volume node
    And Wait for volume 12 restoration from backup 0 completed
    When Activate DR volume 12
    And Attach volume 12
    And Wait for volume 12 healthy
    Then Check volume 12 data is backup 0

DR Volume Node Reboot During Initial Restoration 3
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Initial Restoration
    Given Create volume 03 with    dataEngine=${DATA_ENGINE}
    And Attach volume 03
    And Wait for volume 03 healthy
    And Write data 0 to volume 03
    Then Volume 03 backup 0 should be able to create
    Then Create DR volume 13 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 13 restoration from backup 0 start
    Then Reboot volume 13 volume node
    And Wait for volume 13 restoration from backup 0 completed
    When Activate DR volume 13
    And Attach volume 13
    And Wait for volume 13 healthy
    Then Check volume 13 data is backup 0

DR Volume Node Reboot During Initial Restoration 4
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Initial Restoration
    Given Create volume 04 with    dataEngine=${DATA_ENGINE}
    And Attach volume 04
    And Wait for volume 04 healthy
    And Write data 0 to volume 04
    Then Volume 04 backup 0 should be able to create
    Then Create DR volume 14 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 14 restoration from backup 0 start
    Then Reboot volume 14 volume node
    And Wait for volume 14 restoration from backup 0 completed
    When Activate DR volume 14
    And Attach volume 14
    And Wait for volume 14 healthy
    Then Check volume 14 data is backup 0

DR Volume Node Reboot During Initial Restoration 5
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Initial Restoration
    Given Create volume 05 with    dataEngine=${DATA_ENGINE}
    And Attach volume 05
    And Wait for volume 05 healthy
    And Write data 0 to volume 05
    Then Volume 05 backup 0 should be able to create
    Then Create DR volume 15 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 15 restoration from backup 0 start
    Then Reboot volume 15 volume node
    And Wait for volume 15 restoration from backup 0 completed
    When Activate DR volume 15
    And Attach volume 15
    And Wait for volume 15 healthy
    Then Check volume 15 data is backup 0

DR Volume Node Reboot During Incremental Restoration 1
    [Tags]  manual  longhorn-8425
    [Documentation]    Test DR volume node reboot
    ...                During Incremental Restoration
    Given Create volume 021 with    dataEngine=${DATA_ENGINE}
    And Attach volume 021
    And Wait for volume 021 healthy
    And Write data 0 to volume 021
    Then Volume 021 backup 0 should be able to create
    Then Create DR volume 121 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 121 restoration from backup 0 completed
    Then Write data 1 to volume 021
    And Volume 021 backup 1 should be able to create
    And Wait for volume 121 restoration from backup 1 start
    Then Reboot volume 121 volume node
    Then Wait for volume 121 restoration from backup 1 completed
    And Activate DR volume 121
    And Attach volume 121
    And Wait for volume 121 healthy
    And Check volume 121 data is backup 1

DR Volume Node Reboot During Incremental Restoration 2
    [Tags]  manual  longhorn-8425
    [Documentation]    Test DR volume node reboot
    ...                During Incremental Restoration
    Given Create volume 022 with    dataEngine=${DATA_ENGINE}
    And Attach volume 022
    And Wait for volume 022 healthy
    And Write data 0 to volume 022
    Then Volume 022 backup 0 should be able to create
    Then Create DR volume 122 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 122 restoration from backup 0 completed
    Then Write data 1 to volume 022
    And Volume 022 backup 1 should be able to create
    And Wait for volume 122 restoration from backup 1 start
    Then Reboot volume 122 volume node
    Then Wait for volume 122 restoration from backup 1 completed
    And Activate DR volume 122
    And Attach volume 122
    And Wait for volume 122 healthy
    And Check volume 122 data is backup 1

DR Volume Node Reboot During Incremental Restoration 3
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Incremental Restoration
    Given Create volume 023 with    dataEngine=${DATA_ENGINE}
    And Attach volume 023
    And Wait for volume 023 healthy
    And Write data 0 to volume 023
    Then Volume 023 backup 0 should be able to create
    Then Create DR volume 123 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 123 restoration from backup 0 completed
    Then Write data 1 to volume 023
    And Volume 0 backup 1 should be able to create
    And Wait for volume 123 restoration from backup 1 start
    Then Reboot volume 123 volume node
    Then Wait for volume 123 restoration from backup 1 completed
    And Activate DR volume 123
    And Attach volume 123
    And Wait for volume 123 healthy
    And Check volume 123 data is backup 1

DR Volume Node Reboot During Incremental Restoration 4
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Incremental Restoration
    Given Create volume 024 with    dataEngine=${DATA_ENGINE}
    And Attach volume 024
    And Wait for volume 024 healthy
    And Write data 0 to volume 024
    Then Volume 024 backup 0 should be able to create
    Then Create DR volume 124 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 124 restoration from backup 0 completed
    Then Write data 1 to volume 024
    And Volume 024 backup 1 should be able to create
    And Wait for volume 124 restoration from backup 1 start
    Then Reboot volume 124 volume node
    Then Wait for volume 124 restoration from backup 1 completed
    And Activate DR volume 124
    And Attach volume 124
    And Wait for volume 124 healthy
    And Check volume 124 data is backup 1

DR Volume Node Reboot During Incremental Restoration 5
    [Tags]  manual  longhorn-84251
    [Documentation]    Test DR volume node reboot
    ...                During Incremental Restoration
    Given Create volume 025 with    dataEngine=${DATA_ENGINE}
    And Attach volume 025
    And Wait for volume 025 healthy
    And Write data 0 to volume 025
    Then Volume 025 backup 0 should be able to create
    Then Create DR volume 125 from backup 0    dataEngine=${DATA_ENGINE}
    And Wait for volume 125 restoration from backup 0 completed
    Then Write data 1 to volume 025
    And Volume 025 backup 1 should be able to create
    And Wait for volume 125 restoration from backup 1 start
    Then Reboot volume 125 volume node
    Then Wait for volume 125 restoration from backup 1 completed
    And Activate DR volume 125
    And Attach volume 125
    And Wait for volume 125 healthy
    And Check volume 125 data is backup 1