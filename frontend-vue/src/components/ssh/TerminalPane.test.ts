import { describe, expect, it, vi, beforeEach } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import TerminalPane from './TerminalPane.vue';
import { api, createSshTerminalSocket } from '@/api/client';

interface MockTerminal {
  open: ReturnType<typeof vi.fn>;
  loadAddon: ReturnType<typeof vi.fn>;
  attachCustomKeyEventHandler: ReturnType<typeof vi.fn>;
  onData: ReturnType<typeof vi.fn>;
  onBinary: ReturnType<typeof vi.fn>;
  write: ReturnType<typeof vi.fn>;
  writeln: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  focus: ReturnType<typeof vi.fn>;
  dispose: ReturnType<typeof vi.fn>;
  getSelection: ReturnType<typeof vi.fn>;
  clearSelection: ReturnType<typeof vi.fn>;
  registerMarker: ReturnType<typeof vi.fn>;
  options: Record<string, unknown>;
  cols: number;
  rows: number;
  buffer: {
    active: {
      getLine: ReturnType<typeof vi.fn>;
    };
  };
}

let mockTerminalInstance: MockTerminal;

vi.mock('@xterm/xterm', () => {
  return {
    Terminal: vi.fn().mockImplementation(function (this: MockTerminal) {
      mockTerminalInstance = {
        open: vi.fn(),
        loadAddon: vi.fn(),
        attachCustomKeyEventHandler: vi.fn(),
        onData: vi.fn(),
        onBinary: vi.fn(),
        write: vi.fn(),
        writeln: vi.fn(),
        resize: vi.fn(),
        focus: vi.fn(),
        dispose: vi.fn(),
        getSelection: vi.fn().mockReturnValue('selected command'),
        clearSelection: vi.fn(),
        registerMarker: vi.fn().mockReturnValue({ isDisposed: false, line: 0, dispose: vi.fn() }),
        options: {},
        cols: 80,
        rows: 24,
        buffer: {
          active: {
            getLine: vi.fn().mockReturnValue({
              translateToString: vi.fn().mockReturnValue('echo "hello"'),
            }),
          },
        },
      };
      return mockTerminalInstance;
    }),
  };
});

vi.mock('@xterm/addon-fit', () => {
  return {
    FitAddon: vi.fn().mockImplementation(function () {
      return {
        proposeDimensions: vi.fn().mockReturnValue({ cols: 80, rows: 24 }),
      };
    }),
  };
});

vi.mock('@/api/client', () => {
  return {
    api: {
      prepareSshSession: vi.fn().mockResolvedValue({ ticket: 'test-ticket-xyz' }),
    },
    createSshTerminalSocket: vi.fn().mockImplementation(() => ({
      send: vi.fn(),
      close: vi.fn(),
      readyState: 1, // OPEN
    })),
  };
});

vi.mock('@/lib/clipboard', () => ({
  copyText: vi.fn().mockResolvedValue(true),
}));

if (typeof window !== 'undefined' && !window.ResizeObserver) {
  window.ResizeObserver = vi.fn().mockImplementation(function () {
    return {
      observe: vi.fn(),
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    };
  });
}

describe('TerminalPane.vue', () => {
  const defaultRequest = { host: '192.168.1.100', port: 22, username: 'admin' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders toolbar buttons and initializes terminal on mount', async () => {
    const wrapper = mount(TerminalPane, {
      props: {
        request: defaultRequest,
        active: true,
      },
    });

    expect(wrapper.find('[role="toolbar"]').exists()).toBe(true);
    await flushPromises();
    expect(api.prepareSshSession).toHaveBeenCalledWith(defaultRequest);
    expect(createSshTerminalSocket).toHaveBeenCalledWith('test-ticket-xyz', 80, 24);
  });

  it('handles copy selection button click', async () => {
    const wrapper = mount(TerminalPane, {
      props: {
        request: defaultRequest,
        active: true,
      },
    });

    const buttons = wrapper.findAll('button');
    const copyBtn = buttons.find((b) => b.attributes('aria-label')?.toLowerCase().includes('copy'));
    expect(copyBtn).toBeDefined();
    await copyBtn?.trigger('click');
    expect(mockTerminalInstance.getSelection).toHaveBeenCalled();
  });

  it('handles socket messages and disconnects gracefully', async () => {
    let openHandler: (() => void) | undefined;
    let messageHandler: ((event: MessageEvent) => void) | undefined;
    let closeHandler: (() => void) | undefined;

    vi.mocked(createSshTerminalSocket).mockImplementationOnce(() => ({
      send: vi.fn(),
      close: vi.fn(),
      readyState: 1,
      set onopen(fn: (() => void) | null) {
        openHandler = fn ?? undefined;
      },
      set onmessage(fn: ((event: MessageEvent) => void) | null) {
        messageHandler = fn ?? undefined;
      },
      set onclose(fn: (() => void) | null) {
        closeHandler = fn ?? undefined;
      },
    } as unknown as WebSocket));

    const wrapper = mount(TerminalPane, {
      props: {
        request: defaultRequest,
        active: true,
      },
    });

    await flushPromises();

    // Verify binary data handling
    expect(messageHandler).toBeDefined();
    const binData = new Uint8Array([104, 101, 108, 108, 111]).buffer;
    messageHandler!({ data: binData } as MessageEvent);
    expect(mockTerminalInstance.write).toHaveBeenCalled();

    // Verify control status message handling
    messageHandler!({
      data: JSON.stringify({ type: 'status', stage: 'connected' }),
    } as MessageEvent);
    expect(wrapper.emitted('status')?.at(-1)).toEqual(['connected']);

    // Simulate socket open then close
    expect(openHandler).toBeDefined();
    openHandler!();

    closeHandler!();
    expect(wrapper.emitted('status')?.at(-1)).toEqual(['closed']);
  });

  it('treats close before open as handshake error', async () => {
    let closeHandler: (() => void) | undefined;

    vi.mocked(createSshTerminalSocket).mockImplementationOnce(() => ({
      send: vi.fn(),
      close: vi.fn(),
      readyState: 1,
      set onopen(_fn: (() => void) | null) {},
      set onmessage(_fn: ((event: MessageEvent) => void) | null) {},
      set onclose(fn: (() => void) | null) {
        closeHandler = fn ?? undefined;
      },
    } as unknown as WebSocket));

    const wrapper = mount(TerminalPane, {
      props: {
        request: defaultRequest,
        active: true,
      },
    });

    await flushPromises();

    // Close before open
    closeHandler!();
    expect(wrapper.emitted('status')?.at(-1)).toEqual(['error']);
  });

  it('logs a warning on malformed JSON message rather than swallowing silently', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    let messageHandler: ((event: MessageEvent) => void) | undefined;

    vi.mocked(createSshTerminalSocket).mockImplementationOnce(() => ({
      send: vi.fn(),
      close: vi.fn(),
      readyState: 1,
      set onopen(_fn: (() => void) | null) {},
      set onmessage(fn: ((event: MessageEvent) => void) | null) {
        messageHandler = fn ?? undefined;
      },
      set onclose(_fn: (() => void) | null) {},
    } as unknown as WebSocket));

    mount(TerminalPane, {
      props: {
        request: defaultRequest,
        active: true,
      },
    });

    await flushPromises();

    expect(messageHandler).toBeDefined();
    messageHandler!({ data: 'not-valid-json' } as MessageEvent);
    expect(warnSpy).toHaveBeenCalledWith('Ignoring unparseable terminal message:', expect.any(SyntaxError));
    warnSpy.mockRestore();
  });
});
