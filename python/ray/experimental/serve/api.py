import inspect

import numpy as np

import ray
from ray.experimental.serve.task_runner import RayServeMixin, TaskRunnerActor
from ray.experimental.serve.utils import pformat_color_json, logger
from ray.experimental.serve.global_state import GlobalState

global_state = GlobalState()


def init(blocking=False, object_store_memory=int(1e8)):
    """Initialize a serve cluster.

    Calling `ray.init` before `serve.init` is optional. When there is not a ray
    cluster initialized, serve will call `ray.init` with `object_store_memory`
    requirement.

    Args:
        blocking (bool): If true, the function will wait for the HTTP server to
            be healthy before returns.
        object_store_memory (int): Allocated shared memory size in bytes. The
            default is 100MiB. The default is kept low for latency stability
            reason.
    """
    if not ray.is_initialized():
        ray.init(object_store_memory=object_store_memory)

    # NOTE(simon): Currently the initialization order is fixed.
    # HTTP server depends on the API server.
    global_state.init_api_server()
    global_state.init_router()
    global_state.init_http_server()

    if blocking:
        global_state.wait_until_http_ready()


def create_endpoint_pipeline(pipeline_name, route_expression, blocking=True):
    """Create a service endpoint given route_expression.

    Args:
        endpoint_name (str): A name to associate to the endpoint. It will be
            used as key to set traffic policy.
        route_expression (str): A string begin with "/". HTTP server will use
            the string to match the path.
        blocking (bool): If true, the function will wait for service to be
            registered before returning
    """
    assert pipeline_name in global_state.provisioned_services

    future = global_state.kv_store_actor_handle.register_service.remote(
        route_expression, pipeline_name)
    if blocking:
        ray.get(future)
    global_state.registered_endpoints.add(pipeline_name)

def create_no_http_service(service_name,max_batch_size=1,blocking = True):
    global_state.registered_services.add(service_name)
    future = global_state.router_actor_handle.set_max_batch.remote(service_name,max_batch=max_batch_size)
    if blocking:
        ray.get(future)

def create_backend(func_or_class, backend_tag, num_gpu,*actor_init_args):
    """Create a backend using func_or_class and assign backend_tag.

    Args:
        func_or_class (callable, class): a function or a class implements
            __call__ protocol.
        backend_tag (str): a unique tag assign to this backend. It will be used
            to associate services in traffic policy.
        *actor_init_args (optional): the argument to pass to the class
            initialization method.
    """
    if inspect.isfunction(func_or_class):
        runner = TaskRunnerActor.remote(func_or_class)
    elif inspect.isclass(func_or_class):
        # Python inheritance order is right-to-left. We put RayServeMixin
        # on the left to make sure its methods are not overriden.
        @ray.remote(num_gpus=num_gpu)
        class CustomActor(RayServeMixin, func_or_class):
            pass

        runner = CustomActor.remote(*actor_init_args)
    else:
        raise TypeError(
            "Backend must be a function or class, it is {}.".format(
                type(func_or_class)))

    global_state.backend_actor_handles.append(runner)

    runner._ray_serve_setup.remote(backend_tag,
                                   global_state.router_actor_handle)
    runner._ray_serve_main_loop.remote(runner)

    global_state.registered_backends.add(backend_tag)

# def add_service_to_pipeline(pipeline_name,service_name,blocking=True):
#     assert service_name in global_state.registered_services
#     # assert pipeline_name in global_state.registered_endpoints

#     future = global_state.kv_store_actor_handle_pipeline.add_node.remote(pipeline_name,service_name)
#     if blocking:
#         ray.get(future)

def add_service_dependencies(pipeline_name,service_name_1,service_name_2,blocking=True):
    assert service_name_1 in global_state.registered_services
    assert service_name_2 in global_state.registered_services
    assert pipeline_name not in global_state.provisioned_services

    future = global_state.kv_store_actor_handle_pipeline.add_edge.remote(pipeline_name,service_name_1,service_name_2)
    if blocking:
        ray.get(future)

def provision_pipeline(pipeline_name,blocking=True) :
    assert pipeline_name not in global_state.provisioned_services
    future = global_state.kv_store_actor_handle_pipeline.provision.remote(pipeline_name)
    if blocking : 
        ray.get(future)

    global_state.provisioned_services.add(pipeline_name)


def get_service_dependencies(pipeline_name):
    assert pipeline_name in global_state.provisioned_services
    future = global_state.kv_store_actor_handle_pipeline.get_dependency.remote(pipeline_name)
    return ray.get(future)
def add_service(pipeline_name,service_name,blocking = True):
    assert pipeline_name not in global_state.provisioned_services
    assert service_name in global_state.registered_services
    future = global_state.kv_store_actor_handle_pipeline.add_node.remote(pipeline_name,service_name)
    if blocking : 
        ray.get(future)


def link_service(service_name, backend_tag):
    """Associate a service endpoint with backend tag.

    Example:

    >>> serve.link("service-name", "backend:v1")

    Note:
    This is equivalent to

    >>> serve.split("service-name", {"backend:v1": 1.0})
    """
    assert service_name in global_state.registered_services
    assert backend_tag in global_state.registered_backends

    global_state.router_actor_handle.link.remote(service_name, backend_tag)
    global_state.policy_action_history[service_name].append({backend_tag: 1})


# def split(endpoint_name, traffic_policy_dictionary):
#     """Associate a service endpoint with traffic policy.

#     Example:

#     >>> serve.split("service-name", {
#         "backend:v1": 0.5,
#         "backend:v2": 0.5
#     })

#     Args:
#         endpoint_name (str): A registered service endpoint.
#         traffic_policy_dictionary (dict): a dictionary maps backend names
#             to their traffic weights. The weights must sum to 1.
#     """

#     # Perform dictionary checks
#     assert endpoint_name in global_state.registered_endpoints

#     assert isinstance(traffic_policy_dictionary,
#                       dict), "Traffic policy must be dictionary"
#     prob = 0
#     for backend, weight in traffic_policy_dictionary.items():
#         prob += weight
#         assert (backend in global_state.registered_backends
#                 ), "backend {} is not registered".format(backend)
#     assert np.isclose(
#         prob, 1,
#         atol=0.02), "weights must sum to 1, currently it sums to {}".format(
#             prob)

#     global_state.router_actor_handle.set_traffic.remote(
#         endpoint_name, traffic_policy_dictionary)
#     global_state.policy_action_history[endpoint_name].append(
#         traffic_policy_dictionary)


# def rollback(endpoint_name):
#     """Rollback a traffic policy decision.

#     Args:
#         endpoint_name (str): A registered service endpoint.
#     """
#     assert endpoint_name in global_state.registered_endpoints
#     action_queues = global_state.policy_action_history[endpoint_name]
#     cur_policy, prev_policy = action_queues[-1], action_queues[-2]

#     logger.warning("""
# Current traffic policy is:
# {cur_policy}

# Will rollback to:
# {prev_policy}
# """.format(
#         cur_policy=pformat_color_json(cur_policy),
#         prev_policy=pformat_color_json(prev_policy)))

#     action_queues.pop()
#     global_state.router_actor_handle.set_traffic.remote(
#         endpoint_name, prev_policy)


def get_handle(pipeline_name):
    """Retrieve RayServeHandle for service endpoint to invoke it from Python.

    Args:
        endpoint_name (str): A registered service endpoint.

    Returns:
        RayServeHandle
    """
    assert pipeline_name in global_state.provisioned_services

    # Delay import due to it's dependency on global_state
    from ray.experimental.serve.handle import RayServeHandle

    return RayServeHandle(global_state.kv_store_actor_handle_pipeline,global_state.router_actor_handle, pipeline_name)
