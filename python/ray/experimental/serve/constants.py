#: The interval which http server refreshes its routing table
HTTP_ROUTER_CHECKER_INTERVAL_S = 2

#: Actor name used to register actor nursery
SERVE_NURSERY_NAME = "SERVE_ACTOR_NURSERY"

#: KVStore connector key in bootstrap config
BOOTSTRAP_KV_STORE_CONN_KEY = "kv_store_connector"

#: HTTP Address
DEFAULT_HTTP_ADDRESS = "http://0.0.0.0:8000"

#: HTTP Host
DEFAULT_HTTP_HOST = "0.0.0.0"

#: HTTP Port
DEFAULT_HTTP_PORT = 8000

#: Return ObjectIDs keys for a dictionary
RESULT_KEY = "result"
PREDICATE_KEY = "predicate"

# default value to pass when Enqeueue Predicate is False
PREDICATE_DEFAULT_VALUE = "predicate-false"

#: Default path for profiling services
SERVE_PROFILE_PATH = "/RayServeProfile"
