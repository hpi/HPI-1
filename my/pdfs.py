'''
PDF documents and annotations on your filesystem
'''
REQUIRES = [
    'git+https://github.com/0xabu/pdfannots',
]

from contextlib import redirect_stderr
from datetime import datetime
from dataclasses import dataclass
import io
from pathlib import Path
import time
from typing import NamedTuple, List, Optional, Iterator, Sequence


from my.core import LazyLogger, get_files, Paths, PathIsh
from my.core.cfg import Attrs, make_config
from my.core.common import mcachew, group_by_key
from my.core.error import Res, split_errors


import pdfannots  # type: ignore[import]


from my.config import pdfs as user_config

@dataclass
class pdfs(user_config):
    paths: Paths = ()  # allowed to be empty for 'filelist' logic

    def is_ignored(self, p: Path) -> bool:
        """
        Used to ignore some extremely heavy files
        is_ignored function taken either from config,
        or if not defined, it's a function that returns False
        """
        user_ignore = getattr(user_config, 'is_ignored', None)
        if user_ignore is not None:
            return user_ignore(p)

        return False

    @staticmethod
    def _migration(attrs: Attrs) -> Attrs:
        roots = 'roots'
        if roots in attrs:  # legacy name
            attrs['paths'] = attrs[roots]
            from my.core.warnings import high
            high(f'"{roots}" is deprecated! Use "paths" instead.')
        return attrs


config = make_config(pdfs, migration=pdfs._migration)

logger = LazyLogger(__name__)

def inputs() -> Sequence[Path]:
    # TODO ignoring could be handled on get_files/user config site as well?..
    all_files = get_files(config.paths, glob='**/*.pdf')
    return [p for p in all_files if not config.is_ignored(p)]


# TODO canonical names/fingerprinting?
# TODO defensive if pdf was removed, also cachew key needs to be defensive
class Annotation(NamedTuple):
    path: str
    author: Optional[str]
    page: int
    highlight: Optional[str]
    comment: Optional[str]
    created: Optional[datetime]  # note: can be tz unaware in some bad pdfs...

    @property
    def date(self) -> Optional[datetime]:
        # legacy name
        return self.created


def as_annotation(*, raw_ann, path: str) -> Annotation:
    d = vars(raw_ann)
    d['page'] = raw_ann.page.pageno
    for a in ('boxes', 'rect'):
        if a in d:
            del d[a]
    return Annotation(
        path      = path,
        author    = d['author'],
        page      = d['page'],
        highlight = d['text'],
        comment   = d['contents'],
        created   = d.get('created'),  # todo can be non-defensive once pr is merged
    )


def get_annots(p: Path) -> List[Annotation]:
    b = time.time()
    with p.open('rb') as fo:
        f = io.StringIO()
        with redirect_stderr(f):
            # FIXME
            (annots, outlines) = pdfannots.process_file(fo, emit_progress=False)
            # outlines are kinda like TOC, I don't really need them
    a = time.time()
    took = a - b
    tooks = f'took {took:0.1f} seconds'
    if took > 5:
        tooks = tooks.upper()
    logger.debug('extracting %s %s: %d annotations', tooks, p, len(annots))
    return [as_annotation(raw_ann=a, path=str(p)) for a in annots]
    # TODO stderr?


def _hash_files(pdfs: Sequence[Path]):
    # if mtime hasn't changed then the file hasn't changed either
    return [(pdf, pdf.stat().st_mtime) for pdf in pdfs]


# TODO might make more sense to be more fine grained here, e.g. cache annotations for indifidual files
@mcachew(depends_on=_hash_files)
def _iter_annotations(pdfs: Sequence[Path]) -> Iterator[Res[Annotation]]:
    logger.info('processing %d pdfs', len(pdfs))

    # todo how to print to stdout synchronously?
    # todo global config option not to use pools? useful for debugging..
    from concurrent.futures import ProcessPoolExecutor
    from my.core.common import DummyExecutor
    workers = None  # use 0 for debugging
    Pool = DummyExecutor if workers == 0 else ProcessPoolExecutor
    with Pool(workers) as pool:
        futures = [
            pool.submit(get_annots, pdf)
            for pdf in pdfs
        ]
        for f, pdf in zip(futures, pdfs):
            try:
                yield from f.result()
            except Exception as e:
                logger.error('While processing %s:', pdf)
                logger.exception(e)
                # todo add a comment that it can be ignored... or something like that
                # TODO not sure if should attach pdf as well; it's a bit annoying to pass around?
                # also really have to think about interaction with cachew...
                yield e


def annotations() -> Iterator[Res[Annotation]]:
    pdfs = inputs()
    yield from _iter_annotations(pdfs=pdfs)


class Pdf(NamedTuple):
    path: Path
    annotations: Sequence[Annotation]

    @property
    def created(self) -> Optional[datetime]:
        annots = self.annotations
        return None if len(annots) == 0 else annots[-1].created

    @property
    def date(self) -> Optional[datetime]:
        # legacy
        return self.created


def annotated_pdfs(*, filelist: Optional[Sequence[PathIsh]]=None) -> Iterator[Res[Pdf]]:
    if filelist is not None:
        # hacky... keeping it backwards compatible
        # https://github.com/karlicoss/HPI/pull/74
        config.paths = filelist
    ait = annotations()
    vit, eit = split_errors(ait, ET=Exception)

    for k, g in group_by_key(vit, key=lambda a: a.path).items():
        yield Pdf(path=Path(k), annotations=g)
    yield from eit


from my.core import stat, Stats
def stats() -> Stats:
    return {
        **stat(annotations)   ,
        **stat(annotated_pdfs),
    }


### legacy/misc stuff

# todo retire later if favor of hpi query?
def main() -> None:
    from pprint import pprint
    collected = annotated_pdfs()
    for r in collected:
        if isinstance(r, Exception):
            logger.exception(r)
        else:
            logger.info('collected annotations in: %s', r.path)
            for a in r.annotations:
                pprint(a)

iter_annotations = annotations  # for backwards compatibility
###
