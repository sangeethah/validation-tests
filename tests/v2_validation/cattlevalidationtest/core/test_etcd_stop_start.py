from common_fixtures import *  # NOQA

count = os.environ.get(
    'COUNT', "100")
sleeptime = os.environ.get(
    'ETCD_DOWN_TIME', "900")

TEST_ETCD_DOWN = os.environ.get('TEST_ETCD_DOWN', 'false')

if_test_etcd_down = pytest.mark.skipif(
    TEST_ETCD_DOWN != "True",
    reason='TEST_ETCD_DOWN is set to false')
INSERVICE_SUBDIR = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                'resources/inservicedc')
K8S_SUBDIR = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                          'resources/k8s')


@if_test_etcd_down
def test_etcd_stop_start(client, kube_hosts):
    namespace = "etcd-test-0"
    port = 8080
    create_ns(namespace)
    create_k8_service("service_etcd.yml",
                      namespace,
                      "etcdtest",
                      "etcdtestrc2",
                      "k8s-app=etcdtest-service",
                      scale=1,
                      wait_for_service=True)
    namespace = "etcd-test"
    for n in range(1, int(count)):
        print "Try -" + str(n)
        etcd_stop_start_scenario(client)
        post_check(namespace + "-" + str(n), n+1, port)
        port += 1


@if_test_etcd_down
def test_k8s_upgrade(admin_client, client, kube_hosts, rancher_cli_container):
    cleanup_k8s()
    namespace = "etcd-test-0"
    create_ns(namespace)
    port = 9000
    create_k8_service("service_etcd.yml",
                      namespace,
                      "etcdtest",
                      "etcdtestrc2",
                      "k8s-app=etcdtest-service",
                      scale=1,
                      wait_for_service=True)
    namespace = "etcd-test"
    for n in range(1, int(count)):
        print "Try -" + str(n)
        k8s_upgrade(admin_client, client)
        post_check(namespace + "-" + str(n), n+1, port)
        port += 1


def k8s_upgrade(admin_client, client):

    stack_name = "kubernetes"
    dc_file = "k8s_dc.yml"
    rc_file = "k8s_rc.yml"
    upgrade_option = "--batch-size 1 --interval 1000"
    services = get_all_services(admin_client, stack_name)
    # Upgrade stack using up --upgrade
    upgrade_stack(client, stack_name, services, dc_file, rc_file,
                  upgrade_option=upgrade_option,
                  force_upgrade=True)
    """
    # Confirm upgrade
    service = confirm_upgrade_stack(
        client, stack_name, service, dc_file)
    """


@if_test_etcd_down
def etcd_stop_start_scenario(client, namespace, sleeptime, count):
    env, service = get_env_service_by_name(client, "kubernetes", "etcd")
    # Deactivate etcd Services
    service = service.deactivate()
    service = client.wait_success(service, 300)
    assert service.state == "inactive"
    wait_until_instances_get_stopped_for_service_with_sec_launch_configs(
        client, service, scale=3)

    # sleep for configurable time
    time.sleep(sleeptime)

    # Activate etcd Services
    service = service.activate()
    service = client.wait_success(service, 300)
    assert service.state == "active"
    wait_until_instances_get_running_for_service_with_sec_launch_configs(
        client, service, timeout=300, scale=3)

    print "Etcd started successfully"
    # Wait for K8s stack to become healthy
    env = client.wait_success(env, timeout=300)
    wait_for_condition(
        client, env,
        lambda x: x.healthState == "healthy",
        lambda x: 'State is: ' + x.state,
        timeout=600)
    for service in env.services():
        wait_for_condition(
            client, service,
            lambda x: x.state == "active",
            lambda x: 'State is: ' + x.state,
            timeout=600)
        container_list = get_service_container_list(client, service,
                                                    managed=1)
        for container in container_list:
            if 'io.rancher.container.start_once' not in container.labels:
                assert container.state == "running"
            else:
                assert \
                    container.state == "stopped" or \
                    container.state == "running"


def post_check(namespace, count, ingress_port):
    # Deploy new Namespace
    create_ns(namespace)

    # Add Ingress with 1 target service

    ingress_input_file_name = "ingress_etcd_test.yml"
    ingress_file_name = "ingress_etcd_temp.yml"
    ingress_name = "ingress2"
    port = str(ingress_port)
    ingress_content = readDataFile(K8S_SUBDIR, ingress_input_file_name)
    ingress_content = ingress_content.replace("$port", port)
    with open(os.path.join(K8_SUBDIR, ingress_file_name), "wt") as fout:
        fout.write(ingress_content)
    fout.close()

    services = []
    service1 = {}
    service1["name"] = "k8test2-new"
    service1["selector"] = "k8s-app=k8test2-new-service"
    service1["rc_name"] = "k8testrc2-new"
    service1["filename"] = "ingress_target_services_etcd.yml"
    services.append(service1)

    ingresses = []
    ingress = {}
    ingress["name"] = ingress_name
    ingress["filename"] = ingress_file_name
    ingresses.append(ingress)

    # Create services, ingress and validate
    podnames, lbips = create_service_ingress(ingresses, services,
                                             port, namespace, scale=1)

    print podnames
    print lbips[0]
    check_round_robin_access_lb_ip(podnames[0], lbips[0], port,
                                   path="/name.html")
    # Scale Existing RC
    execute_kubectl_cmds(
        "scale rc etcdtestrc2 --replicas=" +
        str(count)+" --namespace=etcd-test-0")
    waitfor_pods(selector="k8s-app=etcdtest-service",
                 namespace="etcd-test-0", number=count)


def get_all_services(admin_client, stack_name):
    stacks = admin_client.list_stack(name=stack_name)
    assert len(stacks) == 1
    stack_id = stacks[0].id
    services = admin_client.list_service(stackId=stack_id)
    return services


def upgrade_stack(client, stack_name, services, docker_compose,
                  rancher_compose=None, upgrade_option=None,
                  force_upgrade=False):
    if force_upgrade:
        upgrade_cmd = "up --force-upgrade --confirm-upgrade -d "
        final_state = "active"
    else:
        upgrade_cmd = "up --upgrade -d "
        final_state = "upgraded"
    if upgrade_option is not None:
        upgrade_cmd += upgrade_option
    launch_rancher_cli_from_file(
        client, INSERVICE_SUBDIR, stack_name,
        upgrade_cmd, "Upgrading",
        docker_compose, rancher_compose, timeout=12000)
    for service in services:
        service = wait_for_condition(client,
                                     service,
                                     lambda x: x.state == final_state,
                                     lambda x: 'Service state is ' + x.state,
                                     1200)
        service = client.reload(service)
        assert service.state == final_state
    return services


def confirm_upgrade_stack(client, stack_name, services, docker_compose):
    launch_rancher_cli_from_file(
        client, INSERVICE_SUBDIR, stack_name,
        "up --confirm-upgrade -d", "Started",
        docker_compose)
    for service in services:
        service = wait_for_condition(client,
                                     service,
                                     lambda x: x.state == 'active',
                                     lambda x: 'Service state is ' + x.state,
                                     600)
        service = client.reload(service)
        assert service.state == "active"
    return service
