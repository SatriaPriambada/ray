import inspect
from ray.experimental.serve.constants import RESULT_KEY, PREDICATE_KEY


class RequestParams:
    """
    Request Arguments required for enqueuing a request to the service
    queue.

    Args:
        service(str): A registered service endpoint.
        request_context(TaskContext): Context of a request.
        request_slo_ms(float): Expected time for the query to get
            completed.
        return_object_ids(dict[str,ray.ObjectID]): Dictionary of ObjectIds
            where result or predicate of the request will be put. Supported
            keys are: ['result' , 'predicate']
        is_wall_clock_time(bool): if True, router won't add wall clock
            time to `request_slo_ms`.
        return_wall_clock_time(bool): if True, wall clock time for query
            completion will be returned when query is enqueued.

    """

    def __init__(self,
                 service,
                 request_context,
                 request_slo_ms=None,
                 return_object_ids={},
                 is_wall_clock_time=False,
                 return_wall_clock_time=False):

        self.service = service
        self.request_context = request_context
        self.request_slo_ms = request_slo_ms
        if return_object_ids is not None:
            # check for dictionary
            assert isinstance(return_object_ids, dict), ("return_object_ids"
                                                         " must be a "
                                                         "dictionary.")
            # keys must be a subset of return_keys_supproted
            assert (set(return_object_ids.keys()) <= set(
                [RESULT_KEY, PREDICATE_KEY])), ("return_object_ids "
                                                "specified wrongly")
        self.return_object_ids = return_object_ids
        self.is_wall_clock_time = is_wall_clock_time
        self.return_wall_clock_time = return_wall_clock_time
        if request_slo_ms is None:
            self.is_wall_clock_time = False

    @classmethod
    def get_default_kwargs(cls):
        signature = inspect.signature(cls)
        return_dict = {
            k: v.default
            for k, v in signature.parameters.items()
            if v.default is not inspect.Parameter.empty
        }
        val = return_dict.pop("request_slo_ms")
        return_dict["slo_ms"] = val
        return return_dict


class RequestInfo:
    """
    Request Information that will be returned when the request gets enqueued.

    Args:
        result_object_id(list[ray.ObjectID]): Ray ObjectIDs got
            from `RequestParams`.
        return_object_id(bool): If True, `RayServeHandle` remote call
            returns ObjectIDs.
        request_slo_ms(float): The wall clock deadline time of the query.
        return_wall_clock_time(bool): If True, `RayServeHandle` remote call
            returns wall clock deadline time.
    """

    def __init__(self, result_object_id, return_object_id, request_slo_ms,
                 return_wall_clock_time):
        self.result_object_id = result_object_id
        self.return_object_id = return_object_id
        self.request_slo_ms = request_slo_ms
        self.return_wall_clock_time = return_wall_clock_time

    def __iter__(self):
        if self.return_object_id:
            yield self.result_object_id[RESULT_KEY]
        if self.return_wall_clock_time:
            yield self.request_slo_ms

    @staticmethod
    def wait_for_requestInfo(request_params):
        if (RESULT_KEY not in request_params.return_object_ids
                or request_params.return_wall_clock_time):
            return True
        return False
