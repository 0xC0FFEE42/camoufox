import asyncio
import json
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional, Union, overload

from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    PlaywrightContextManager,
)
from typing_extensions import Literal

from camoufox.virtdisplay import VirtualDisplay
from .utils import async_attach_vd, launch_options


class AsyncCamoufox(PlaywrightContextManager):
    """
    Wrapper around playwright.async_api.PlaywrightContextManager that automatically
    launches a browser and closes it when the context manager is exited.
    """

    def __init__(
            self,
            fingerprint_path: Optional[Union[str, Path]] = None,
            storage_state_path: Optional[Union[str, Path]] = None,
            user_data_dir: Optional[Union[str, Path]] = None,
            **launch_kwargs,
    ):
        super().__init__()
        self.browser: Optional[Union[Browser, BrowserContext]] = None

        self.fingerprint_path = Path(fingerprint_path).resolve() if fingerprint_path else None
        self.storage_state_path = Path(storage_state_path).resolve() if storage_state_path else None
        self.user_data_dir = Path(user_data_dir).resolve() if user_data_dir else None
        self.launch_kwargs = launch_kwargs

    async def __aenter__(self) -> Union[Browser, BrowserContext]:
        _playwright = await super().__aenter__()

        # Load launch options from fingerprint cache or regenerate
        if self.fingerprint_path and self.fingerprint_path.exists():
            try:
                from_options = json.loads(self.fingerprint_path.read_text())
            except Exception:
                from_options = await self._generate_launch_options()
        else:
            from_options = await self._generate_launch_options()

        if self.user_data_dir:
            self.browser = await _playwright.firefox.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                **from_options,
            )
        elif self.storage_state_path:
            if not self.storage_state_path.exists():
                self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
                self.storage_state_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
            browser = await _playwright.firefox.launch(**from_options)
            context = await browser.new_context(storage_state=str(self.storage_state_path))
            self.browser = context
        else:
            browser = await _playwright.firefox.launch(**from_options)
            self.browser = await browser.new_context()

        return self.browser

    async def __aexit__(self, *args: Any):
        if self.storage_state_path and isinstance(self.browser, BrowserContext):
            await self.browser.storage_state(path=str(self.storage_state_path))
        if self.browser:
            await self.browser.close()
        await super().__aexit__(*args)

    async def _generate_launch_options(self) -> Dict[str, Any]:
        from_options = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(launch_options, **self.launch_kwargs),
        )
        if self.fingerprint_path:
            self.fingerprint_path.parent.mkdir(parents=True, exist_ok=True)
            self.fingerprint_path.write_text(json.dumps(from_options), encoding="utf-8")
        return from_options


@overload
async def AsyncNewBrowser(
        playwright: Playwright,
        *,
        from_options: Optional[Dict[str, Any]] = None,
        persistent_context: Literal[False] = False,
        **kwargs,
) -> Browser: ...


@overload
async def AsyncNewBrowser(
        playwright: Playwright,
        *,
        from_options: Optional[Dict[str, Any]] = None,
        persistent_context: Literal[True],
        **kwargs,
) -> BrowserContext: ...


async def AsyncNewBrowser(
        playwright: Playwright,
        *,
        headless: Optional[Union[bool, Literal['virtual']]] = None,
        from_options: Optional[Dict[str, Any]] = None,
        persistent_context: bool = False,
        debug: Optional[bool] = None,
        **kwargs,
) -> Union[Browser, BrowserContext]:
    if headless == 'virtual':
        virtual_display = VirtualDisplay(debug=debug)
        kwargs['virtual_display'] = virtual_display.get()
        headless = False
    else:
        virtual_display = None

    if not from_options:
        from_options = await asyncio.get_event_loop().run_in_executor(
            None,
            partial(launch_options, headless=headless, debug=debug, **kwargs),
        )

    if persistent_context:
        context = await playwright.firefox.launch_persistent_context(**from_options)
        return await async_attach_vd(context, virtual_display)

    browser = await playwright.firefox.launch(**from_options)
    return await async_attach_vd(browser, virtual_display)