'''
TODO doesn't really belong to 'core' morally, but can think of moving out later
'''
from .common import assert_subpackage; assert_subpackage(__name__)

from typing import Iterable, Any, Optional, Dict

from .common import LazyLogger, asdict, Json


logger = LazyLogger(__name__)


class config:
    db = 'db'


def fill(it: Iterable[Any], *, measurement: str, reset: bool=False, dt_col: str='dt') -> None:
    # todo infer dt column automatically, reuse in stat?
    # it doesn't like dots, ends up some syntax error?
    measurement = measurement.replace('.', '_')
    # todo autoinfer measurement?

    db = config.db

    from influxdb import InfluxDBClient # type: ignore
    client = InfluxDBClient()
    # todo maybe create if not exists?
    # client.create_database(db)

    # todo should be it be env variable?
    if reset:
        client.delete_series(database=db, measurement=measurement)

    # TODO need to take schema here...
    cache: Dict[str, bool] = {}
    def good(f, v) -> bool:
        c = cache.get(f)
        if c is not None:
            return c
        t = type(v)
        r = t in {str, int}
        cache[f] = r
        if not r:
            logger.warning('%s: filtering out %s=%s because of type %s', measurement, f, v, t)
        return r

    def filter_dict(d: Json) -> Json:
        return {f: v for f, v in d.items() if good(f, v)}

    def dit() -> Iterable[Json]:
        for i in it:
            d = asdict(i)
            tags: Optional[Json] = None
            tags_ = d.get('tags') # meh... handle in a more robust manner
            if tags_ is not None and isinstance(tags_, dict): # FIXME meh.
                del d['tags']
                tags = tags_

            # TODO what to do with exceptions??
            # todo handle errors.. not sure how? maybe add tag for 'error' and fill with empty data?
            dt = d[dt_col].isoformat()
            del d[dt_col]

            fields = filter_dict(d)

            yield dict(
                measurement=measurement,
                # TODO maybe good idea to tag with database file/name? to inspect inconsistencies etc..
                # hmm, so tags are autoindexed and might be faster?
                # not sure what's the big difference though
                # "fields are data and tags are metadata"
                tags=tags,
                time=dt,
                fields=fields,
            )


    from more_itertools import chunked
    # "The optimal batch size is 5000 lines of line protocol."
    # some chunking is def necessary, otherwise it fails
    for chi in chunked(dit(), n=5000):
        chl = list(chi)
        logger.debug('writing next chunk %s', chl[-1])
        client.write_points(chl, database=db)
    # todo "Specify timestamp precision when writing to InfluxDB."?


def magic_fill(it, *, name: Optional[str]=None) -> None:
    if name is None:
        assert callable(it) # generators have no name/module
        name = f'{it.__module__}:{it.__name__}'
    assert name is not None

    if callable(it):
        it = it()

    from itertools import tee
    from more_itertools import first, one
    it, x = tee(it)
    f = first(x, default=None)
    if f is None:
        logger.warning('%s has no data', name)
        return

    # TODO can we reuse pandas code or something?
    #
    from .pandas import _as_columns
    schema = _as_columns(type(f))

    from datetime import datetime
    dtex = RuntimeError(f'expected single datetime field. schema: {schema}')
    dtf = one((f for f, t in schema.items() if t == datetime), too_short=dtex, too_long=dtex)

    fill(it, measurement=name, reset=True, dt_col=dtf)
