"""VfsProvider — the contract every filesystem backend implements.

A provider owns one ``scheme`` (``file``, ``zip``, ``sftp``, ``docker`` …) and
turns a :class:`VfsPath` into listings, byte streams, and mutations. The panel
and the copy engine talk only to this protocol, so a new backend (an archive,
an SFTP server, a JSON API) becomes a panel by implementing it — nothing in the
UI changes.

Progress / cancellation deliberately mirror :mod:`dunders.fm.actions`
(``on_progress(index, total)`` + a :class:`threading.Event`) so the existing
worker-thread + ProgressDialog plumbing in ``app.py`` is reused unchanged.

Layering note: ``FileEntry`` and ``OpResult`` still live under ``dunders.fm``.
They are fundamentally VFS data types and are expected to migrate into
``dunders.core`` in a later step; until then they are referenced here only
under ``TYPE_CHECKING`` (annotations are strings via ``from __future__``), so
there is no runtime ``core → fm`` import cycle.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, BinaryIO, Protocol, runtime_checkable

from dunders.core.vfs.locator import VfsPath

if TYPE_CHECKING:
    from dunders.fm.actions import OpResult
    from dunders.fm.file_entry import FileEntry


__all__ = ["VfsProvider", "ProgressCallback", "TargetResolver"]

ProgressCallback = Callable[[int, int], None]


@runtime_checkable
class VfsProvider(Protocol):
    scheme: str
    capabilities: frozenset[str]   # {"read","write","stream","random_access","watch"}

    def scan(
        self,
        loc: VfsPath,
        *,
        show_hidden: bool = False,
        include_parent: bool = True,
    ) -> list[FileEntry]: ...

    def is_dir(self, loc: VfsPath) -> bool:
        """Whether ``loc`` is a directory. Used by the generic transfer engine
        to decide between recursing and streaming bytes."""
        ...

    def open_read(self, loc: VfsPath) -> BinaryIO: ...

    def open_write(
        self, loc: VfsPath, *, size_hint: int | None = None, overwrite: bool = False
    ) -> BinaryIO:
        """Open a member/file for writing. ``overwrite=True`` replaces an
        existing target (used when editing a member in place); the default
        refuses an existing member so copies never clobber silently."""
        ...

    def mkdir(self, parent: VfsPath, name: str) -> OpResult: ...

    def delete(
        self,
        targets: list[VfsPath],
        *,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OpResult: ...

    # Intra-provider fast paths — optional. The transfer engine falls back to
    # generic streaming when these return ``None``. ``rename_to`` overrides the
    # destination basename when there is exactly one source (copy-with-rename).
    def copy_within(
        self,
        sources: list[VfsPath],
        dest: VfsPath,
        *,
        rename_to: str | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OpResult | None: ...

    def move_within(
        self,
        sources: list[VfsPath],
        dest: VfsPath,
        *,
        rename_to: str | None = None,
        on_progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> OpResult | None: ...


@runtime_checkable
class TargetResolver(Protocol):
    """Optional capability: turn a typed ``<scheme>:<spec>`` destination into a
    write-target locator, creating the archive/connection if needed.

    A provider *declares its prefix* simply as its ``scheme`` and opts into
    "create on copy" by implementing this. When an F5 copy destination starts
    with ``<scheme>:``, the app hands the part after the colon to the matching
    provider's ``resolve_target`` and copies the selection into the returned
    locator (then opens it in the panel). Examples:

    - ``zip:backup.zip`` → a new ``zip`` archive at ``<base>/backup.zip``.
    - ``ftp:user@host/path`` → an opened ``ftp`` connection rooted there.

    Kept separate from :class:`VfsProvider` (not all providers create targets),
    so it is checked structurally via ``getattr``/``isinstance``.
    """

    scheme: str

    def resolve_target(self, spec: str, *, base: VfsPath) -> VfsPath | None:
        """``spec`` is the text after ``<scheme>:``. ``base`` is the destination
        panel's location (where a relative target is created). Return the target
        locator, or ``None`` if this provider can't take ``spec`` here."""
        ...
