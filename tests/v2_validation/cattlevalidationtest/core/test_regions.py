from common_fixtures import *  # NOQA
REGIONS_SUBDIR = \
    os.path.join(os.path.dirname(os.path.realpath(__file__)),
                 'resources/regions')

REGION = os.environ.get('REGION_NAME', "region1")
subnet_octet_start = os.environ.get('SUBNET_OCTET_START', "10")
test_regions = os.environ.get('TEST_REGIONS', "False")

if_test_regions = pytest.mark.skipif(test_regions != "True",
                                     reason="No Regions testing")

SERVICE_ACCOUNT_NAME = "sa-region"
policy_within_linked = {"within": "linked", "action": "allow"}
subnet_octet = int(subnet_octet_start)
subnet = "10.42.0.0/16"

project1 = {"template_name": "subnet"+str(subnet_octet),
            "project_name": "test1"+REGION,
            "subnet_start": "10.42."+str(subnet_octet)+".2",
            "subnet_end": "10.42."+str(subnet_octet)+".200"}
subnet_octet += 10
project2 = {"template_name": "subnet"+str(subnet_octet),
            "project_name": "test2"+REGION,
            "subnet_start": "10.42."+str(subnet_octet)+".2",
            "subnet_end": "10.42."+str(subnet_octet)+".200"}
subnet_octet += 10
project3 = {"template_name": "subnet"+str(subnet_octet),
            "project_name": "test3"+REGION,
            "subnet_start": "10.42."+str(subnet_octet)+".2",
            "subnet_end": "10.42."+str(subnet_octet)+".200"}

project_settings = [project1, project2, project3]

jinja_input_config = {"region1": REGION,
                      "project1": project_settings[0]["project_name"],
                      "project2": project_settings[1]["project_name"],
                      "project3": project_settings[2]["project_name"],
                      "lb_image": get_haproxy_image()[7:]}

SLEEP_INTERVAL = int(os.environ.get('SLEEP_INTERVAL', "10"))


@if_test_regions
def test_setup_single_region(admin_user_client):
    sa_key = create_service_account(admin_user_client)
    create_region_entries(admin_user_client, REGION, sa_key,
                          rancher_server_url(), local=True)
    for project_setting in project_settings:
        project_template = \
            create_template_with_subnet(admin_user_client,
                                        project_setting["template_name"],
                                        subnet,
                                        project_setting["subnet_start"],
                                        project_setting["subnet_end"])
        project = admin_user_client.create_project(
            name=project_setting["project_name"],
            projectTemplateId=project_template.id)
        project = admin_user_client.wait_success(project)
        assert project.state == "active"
        wait_for_condition(
            admin_user_client, project,
            lambda x: x.defaultNetworkId is not None,
            lambda x: 'State is: ' + x.defaultNetworkId)
    for project_setting in project_settings:
        project = get_project_by_name(admin_user_client,
                                      project_setting["project_name"])
        client = client_for_project(project)
        setNetworkPolicy(admin_user_client, project,
                         "deny", policy_within_linked)
        add_digital_ocean_hosts(client, 2, size="1gb",
                                docker_version="1.12",
                                wait_for_success=False)


@if_test_regions
def test_cross_env_links(admin_user_client, request):
    project1 = get_project_by_name(admin_user_client,
                                   project_settings[0]["project_name"])
    client1 = client_for_project(project1)

    project2 = get_project_by_name(admin_user_client,
                                   project_settings[1]["project_name"])
    client2 = client_for_project(project2)

    project3 = get_project_by_name(admin_user_client,
                                   project_settings[2]["project_name"])
    client3 = client_for_project(project3)

    rancher_cli_container(client1, request)

    create_template_for_jinja(REGIONS_SUBDIR, "region1.yml.j2",
                              jinja_input_config, "region1.yml")

    create_template_for_jinja(REGIONS_SUBDIR, "region1-rc.yml.j2",
                              jinja_input_config, "region1-rc.yml")

    env1 = create_stack_with_service(client1, "stack1", REGIONS_SUBDIR,
                                     "region1.yml", "region1-rc.yml")
    assert len(env1.services()) == 2
    service1 = get_service_by_name(client1, env1, "test1")
    lb_service1 = get_service_by_name(client1, env1, "lb-1")

    env2 = create_stack_with_service(client2, "stack2", REGIONS_SUBDIR,
                                     "region2.yml")
    assert len(env2.services()) == 2

    linked_service1 = get_service_by_name(client2, env2, "linked1")
    lb_target1 = get_service_by_name(client2, env2, "target1")

    env3 = create_stack_with_service(client3, "stack3", REGIONS_SUBDIR,
                                     "region3.yml")
    assert len(env1.services()) == 2

    linked_service2 = get_service_by_name(client3, env3, "linked2")
    lb_target2 = get_service_by_name(client3, env3, "target2")

    validate_lb_service(client2, lb_service1, "9000", [lb_target1],
                        lb_client=client1)
    validate_linked_service(client1, service1, [linked_service1], "9001",
                            linkName="myweb",
                            linked_service_client=client2)

    # Update cross environment links to point to different environment
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update.yml.j2",
                              jinja_input_config, "region1-update.yml")
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update-rc.yml.j2",
                              jinja_input_config, "region1-update-rc.yml")
    update_stack(client1, "stack1", service1,
                 "region1-update.yml", "region1-update-rc.yml",
                 directory=REGIONS_SUBDIR,
                 project=project1)
    time.sleep(SLEEP_INTERVAL)

    validate_lb_service(client3, lb_service1, "9000", [lb_target2],
                        lb_client=client1)
    validate_linked_service(client1, service1, [linked_service2], "9001",
                            linkName="myweb",
                            linked_service_client=client3)

    # Update cross environment links to point to an additional environment
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update2.yml.j2",
                              jinja_input_config, "region1-update2.yml")
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update2-rc.yml.j2",
                              jinja_input_config, "region1-update2-rc.yml")
    update_stack(client1, "stack1", service1,
                 "region1-update2.yml", "region1-update2-rc.yml",
                 directory=REGIONS_SUBDIR,
                 project=project1)
    time.sleep(SLEEP_INTERVAL)

    lb_target_con_names = \
        get_container_names_list(client2, [lb_target1]) + \
        get_container_names_list(client3, [lb_target2])

    validate_lb_service_con_names(client1, lb_service1, "9000",
                                  lb_target_con_names)
    validate_linked_service(client1, service1, [linked_service2], "9001",
                            linkName="myweb",
                            linked_service_client=client3)
    validate_linked_service(client1, service1, [linked_service1], "9001",
                            linkName="myweb2",
                            linked_service_client=client2)

    # Update cross environment links to remove existing links
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update2.yml.j2",
                              jinja_input_config, "region1-update2.yml")
    create_template_for_jinja(REGIONS_SUBDIR, "region1-update2-rc.yml.j2",
                              jinja_input_config, "region1-update2-rc.yml")
    update_stack(client1, "stack1", service1,
                 "region1.yml", "region1-rc.yml",
                 directory=REGIONS_SUBDIR,
                 project=project1)
    time.sleep(SLEEP_INTERVAL)

    lb_target_con_names = get_container_names_list(client2, [lb_target1])
    validate_lb_service_con_names(client1, lb_service1, "9000",
                                  lb_target_con_names)
    validate_linked_service(client1, service1, [linked_service1], "9001",
                            linkName="myweb",
                            linked_service_client=client2)


def create_region_entries(client, region_name, sa_key, url, local=True):
    region = client.create_region(name=region_name,
                                  publicValue=sa_key.publicValue,
                                  secretValue=sa_key.secretValue,
                                  url=url,
                                  local=True)
    return region


def create_service_account(client):
    sa = client.create_account(name=SERVICE_ACCOUNT_NAME,
                               kind="service")
    assert sa.name == SERVICE_ACCOUNT_NAME
    assert sa.kind == "service"

    # service account will be used for cross-environment agent creation
    sa_key = client.create_api_key(accountId=sa.id)
    assert sa_key.state == 'registering'
    assert sa_key.accountId == sa.id
    return sa_key


def setNetworkPolicy(client, project, defaultPolicyAction, policy):

    assert project.defaultNetworkId is not None
    """
    network = client.by_id('network', project.defaultNetworkId)
    network = client.update(
        network,
        defaultPolicyAction=defaultPolicyAction,
        policy=policy)
    network = wait_success(client, network)
    assert network.defaultPolicyAction == defaultPolicyAction

    """
    projects = client.list_project(name=project.name, include="networks")
    assert len(projects) == 1
    for network in projects[0].networks():
        print network.name
        if network.name == "ipsec":
            network = client.update(
                network,
                defaultPolicyAction=defaultPolicyAction,
                policy=policy)
            network = wait_success(client, network)
            assert network.defaultPolicyAction == defaultPolicyAction
            return
    assert False
