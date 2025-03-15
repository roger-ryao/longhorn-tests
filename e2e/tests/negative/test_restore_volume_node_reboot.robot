*** Settings ***
Documentation    The node the restore volume attached to is down
...              - Issue: https://github.com/longhorn/longhorn/issues/9865
...              - https://github.com/longhorn/longhorn/issues/1355
...              - Test the restoration process of a Longhorn volume when the attached node goes down.
...              - Includes verification for both encrypted and non-encrypted volumes.

Test Tags    manual  longhorn-9865

Resource    ../keywords/variables.resource
Resource    ../keywords/common.resource
Resource    ../keywords/longhorn.resource
Resource    ../keywords/host.resource
Resource    ../keywords/volume.resource
Resource    ../keywords/snapshot.resource
Resource    ../keywords/backup.resource
Resource    ../keywords/k8s.resource


Test Setup    Set test environment
Test Teardown    Cleanup test resources
Test Template    Restore volume attached node is down

*** Keywords ***
Restore volume attached node is down
    [Arguments]    ${description}    ${encrypted}
    Given Create volume 0 with    dataEngine=${DATA_ENGINE}    encrypted=${encrypted}
    And Attach volume 0
    And Wait for volume 0 healthy
    And Write data 0 to volume 0
    Then Volume 0 backup 0 should be able to create

    FOR    ${i}    IN RANGE    ${LOOP_COUNT}
        When Create volume 1 from backup 0 of volume 0  dataEngine=${DATA_ENGINE}  wait_attached=True  encrypted=${encrypted}
        And Wait for volume 1 restoration from backup 0 of volume 0 start
        And Power off volume 1 volume node without waiting
        And Wait for volume 1 restoration to complete

        Then Attach volume 1 to healthy node
        And Wait for volume 1 degraded
        Then Check volume 1 data is backup 0 of volume 0

        Then Detach volume 1 from attached node
        And Delete volume 1
        And Power on off nodes
    END

*** Test Cases ***
The Restore Volume attached node is down
    Non-Encrypted Volume    false
    Encrypted Volume    true
