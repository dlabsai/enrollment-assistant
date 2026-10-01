// @vitest-environment happy-dom
import assert from "node:assert/strict";

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, test } from "vitest";

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@va/shared/components/ui/dropdown-menu";
import { ScrollArea } from "@va/shared/components/ui/scroll-area";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
});

afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
});

test("ScrollArea tracks overflow direction and pointer hover", async () => {
    const setViewportMetrics = (element: HTMLDivElement | null): void => {
        if (!element) {
            return;
        }
        Object.defineProperties(element, {
            clientHeight: { configurable: true, get: () => 100 },
            clientWidth: { configurable: true, get: () => 100 },
            scrollHeight: { configurable: true, get: () => 200 },
            scrollTop: { configurable: true, writable: true, value: 0 },
            scrollWidth: { configurable: true, get: () => 100 },
        });
    };

    await act(async () =>
        root.render(
            createElement(ScrollArea, {
                overflowFadeClassName: "from-popover",
                viewportProps: { style: { overflowX: "hidden" } },
                viewportRef: setViewportMetrics,
                viewportRender: createElement(
                    "div",
                    { "data-testid": "list", role: "listbox" },
                    createElement("div", { role: "option" }, "First option"),
                ),
            }),
        ),
    );

    const list = host.querySelector<HTMLDivElement>('[data-testid="list"]');
    const scrollArea = host.querySelector('[data-slot="scroll-area"]');
    const scrollbar = host.querySelector('[data-slot="scroll-area-scrollbar"]');
    assert.ok(list);
    assert.ok(scrollArea);
    assert.ok(scrollbar);
    assert.equal(list.getAttribute("role"), "listbox");
    assert.equal(
        list.querySelector('[role="option"]')?.textContent,
        "First option",
    );
    assert.equal(list.style.overflowX, "hidden");
    assert.equal(scrollArea.hasAttribute("data-overflow-y-start"), false);
    assert.equal(scrollArea.hasAttribute("data-overflow-y-end"), true);

    await act(async () => {
        list.dispatchEvent(
            new PointerEvent("pointermove", {
                bubbles: true,
                pointerType: "mouse",
            }),
        );
    });
    assert.equal(scrollbar.hasAttribute("data-hovering"), true);

    await act(async () => {
        list.scrollTop = 100;
        list.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    assert.equal(scrollArea.hasAttribute("data-overflow-y-start"), true);
    assert.equal(scrollArea.hasAttribute("data-overflow-y-end"), false);
});

test("DropdownMenuContent retains menu semantics as a ScrollArea viewport", async () => {
    await act(async () =>
        root.render(
            createElement(
                DropdownMenu,
                { open: true },
                createElement(DropdownMenuTrigger, null, "Actions"),
                createElement(
                    DropdownMenuContent,
                    null,
                    createElement(DropdownMenuItem, null, "First action"),
                ),
            ),
        ),
    );

    const popup = document.querySelector('[data-slot="dropdown-menu-content"]');
    assert.ok(popup);
    assert.equal(popup.getAttribute("role"), "menu");
    assert.equal(popup.getAttribute("tabindex"), "-1");
    assert.equal(
        popup.querySelector('[role="menuitem"]')?.textContent,
        "First action",
    );
});
