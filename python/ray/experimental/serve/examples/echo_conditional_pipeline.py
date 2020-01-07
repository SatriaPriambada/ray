"""
Ray serve conditional pipeline example
"""
import ray
import ray.experimental.serve as serve
from ray.experimental.serve import BackendConfig

# initialize ray serve system.
# blocking=True will wait for HTTP server to be ready to serve request.
serve.init(blocking=True)


# This is an example of conditional backend implementation
def echo_v1(_, num):
    return num


def echo_v1_predicate(num):
    return num < 0.5


def echo_v2(_, relay=""):
    return f"echo_v2({relay})"


def echo_v3(_, relay=""):
    return f"echo_v3({relay})"


# an endpoint is associated with an http URL.
serve.create_endpoint("my_endpoint1", "/echo1")
serve.create_endpoint("my_endpoint2", "/echo2")
serve.create_endpoint("my_endpoint3", "/echo3")

# create backends
serve.create_backend(
    echo_v1,
    "echo:v1",
    backend_config=BackendConfig(enable_predicate=True),
    predicate_function=echo_v1_predicate)
serve.create_backend(echo_v2, "echo:v2")
serve.create_backend(echo_v3, "echo:v3")

# link service to backends
serve.link("my_endpoint1", "echo:v1")
serve.link("my_endpoint2", "echo:v2")
serve.link("my_endpoint3", "echo:v3")

# get the handle of the endpoints
handle1 = serve.get_handle("my_endpoint1")
handle2 = serve.get_handle("my_endpoint2")
handle3 = serve.get_handle("my_endpoint3")

for number in [0.2, 0.8]:
    first_object_id = ray.ObjectID.from_random()
    predicate_object_id = ray.ObjectID.from_random()
    handle1.remote(
        num=number,
        return_object_ids={
            serve.RESULT_KEY: first_object_id,
            serve.PREDICATE_KEY: predicate_object_id
        })
    second_object_id = ray.ObjectID.from_random()

    return_val = handle2.remote(
        relay=first_object_id,
        predicate_condition=predicate_object_id,
        default_value=("kwargs", "relay"),
        return_object_ids={serve.RESULT_KEY: second_object_id})

    assert return_val is None
    result = ray.get(handle3.remote(relay=second_object_id))
    print("For number : {} the whole pipeline output is : {}".format(
        number, result))
