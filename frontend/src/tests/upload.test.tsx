import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ImportsPage } from "../pages/Imports";
function mount() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <ImportsPage canWrite />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
afterEach(() => vi.unstubAllGlobals());
it("导入失败逐项显示安全字段、批次错误和截断，不把首个错误冒充完整报告", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            init.method === "POST"
              ? { job_id: "job" }
              : url.endsWith("/jobs/job")
                ? {
                    id: "job",
                    state: "FAILED",
                    attempts: 1,
                    error_message: "材料校验失败",
                    result: {
                      validation_report: {
                        valid: false,
                        total_rows: 200,
                        error_count: 120,
                        errors: [
                          {
                            row: 0,
                            field_path: "evidence",
                            error_code: "BATCH_EVIDENCE",
                            message: "批次证据无效",
                          },
                          {
                            row: 2,
                            unit_id: "u2",
                            field_path: "gold.answer_points",
                            error_code: "EMPTY_POINTS",
                            message: "要点不能为空",
                          },
                        ],
                        truncated: true,
                      },
                    },
                  }
                : { items: [], total: 0 },
          ),
          { status: 200 },
        ),
      ),
    ),
  );
  mount();
  fireEvent.change(screen.getByLabelText("契约JSON内容"), {
    target: { value: '{"mode":"demo"}' },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交接入校验" }));
  expect(
    await screen.findByRole("columnheader", { name: "字段路径" }),
  ).toBeInTheDocument();
  expect(screen.getByText("gold.answer_points")).toBeInTheDocument();
  expect(screen.getByText("批次 / 契约")).toBeInTheDocument();
  expect(screen.getByText(/共120项错误/)).toBeInTheDocument();
  expect(screen.getByText(/报告已截断/)).toBeInTheDocument();
});
it("真实读取JSONL文件并将报告及原文索引作为同一受控包装提交", async () => {
  const calls: Record<string, unknown>[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      if (url.endsWith("/imports/upload"))
        calls.push(JSON.parse(String(init.body)));
      return Promise.resolve(
        new Response(
          JSON.stringify(
            init.method === "POST"
              ? {
                  job_id: "upload-job",
                  raw_file_sha256: "a".repeat(64),
                  normalized_sha256: "b".repeat(64),
                  validation_report: {
                    valid: true,
                    total_rows: 1,
                    error_count: 0,
                    errors: [],
                    truncated: false,
                  },
                }
              : url.includes("/jobs/")
                ? { id: "upload-job", state: "SUCCEEDED", attempts: 1 }
                : { items: [], total: 0 },
          ),
          { status: 200 },
        ),
      );
    }),
  );
  mount();
  const file = new File(['{"unit_id":"u1"}\n'], "units.jsonl", {
    type: "application/x-ndjson",
  });
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode('{"unit_id":"u1"}\n').buffer,
  });
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [file] },
  });
  fireEvent.change(screen.getByLabelText("契约与S3报告JSON（不含units）"), {
    target: { value: '{"mode":"demo","batch_id":"demo1"}' },
  });
  fireEvent.change(screen.getByLabelText("原文索引JSON（可选）"), {
    target: { value: '{"d":{"doc_id":"d","text":"原文"}}' },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "提交JSONL受控上传" }),
  );
  expect(await screen.findByText(/原始文件SHA-256/)).toBeInTheDocument();
  expect(calls).toEqual([
    {
      filename: "units.jsonl",
      units_jsonl: '{"unit_id":"u1"}\n',
      envelope: { mode: "demo", batch_id: "demo1" },
      source_index: { d: { doc_id: "d", text: "原文" } },
    },
  ]);
});
it("上传422保留批次及逐行错误明细，不把失败显示为完成", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((_url: string, init: RequestInit) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            init.method === "POST"
              ? {
                  error_code: "UPLOAD_INVALID",
                  message: "上传校验失败",
                  request_id: "req-upload",
                  details: {
                    validation_report: {
                      valid: false,
                      total_rows: 2,
                      error_count: 1,
                      truncated: false,
                      errors: [
                        {
                          row: 2,
                          field_path: "contexts",
                          error_code: "SOURCE_MISSING",
                          message: "原文索引缺失",
                        },
                      ],
                    },
                  },
                }
              : { items: [], total: 0 },
          ),
          { status: init.method === "POST" ? 422 : 200 },
        ),
      ),
    ),
  );
  mount();
  const file = new File(["{}"], "units.jsonl");
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode("{}").buffer,
  });
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [file] },
  });
  fireEvent.change(screen.getByLabelText("契约与S3报告JSON（不含units）"), {
    target: { value: '{"mode":"demo"}' },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "提交JSONL受控上传" }),
  );
  expect(await screen.findByText("SOURCE_MISSING")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("req-upload");
  expect(screen.queryByText(/原始文件SHA-256/)).not.toBeInTheDocument();
});
function localFile(name: string, text: string) {
  const file = new File([text], name);
  Object.defineProperty(file, "arrayBuffer", {
    value: async () => new TextEncoder().encode(text).buffer,
  });
  return file;
}
it("JSONL伴随报告与原文索引文件真正读取，拒绝包装中的重复units", async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit) => {
      if (init.method === "POST") calls.push(url);
      return Promise.resolve(
        new Response('{"items":[],"total":0}', { status: 200 }),
      );
    }),
  );
  mount();
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [localFile("units.jsonl", "{}")] },
  });
  fireEvent.change(screen.getByLabelText("选择契约与S3报告文件（可选）"), {
    target: { files: [localFile("report.json", '{"mode":"demo","units":[]}')] },
  });
  fireEvent.change(screen.getByLabelText("选择原文索引文件（可选）"), {
    target: { files: [localFile("index.json", '{"d":{"doc_id":"d"}}')] },
  });
  expect(
    await screen.findByDisplayValue('{"d":{"doc_id":"d"}}'),
  ).toBeInTheDocument();
  fireEvent.click(
    await screen.findByRole("button", { name: "提交JSONL受控上传" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("不得含units");
  expect(calls).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("契约与S3报告JSON（不含units）"), {
    target: { value: "[]" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提交JSONL受控上传" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("JSON对象");
});
it("JSONL读取拒绝非法文件名及超大文件，索引条目须为对象", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(new Response('{"items":[],"total":0}', { status: 200 })),
    ),
  );
  mount();
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [localFile("wrong.txt", "{}")] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("以.jsonl结尾");
  const large = localFile("large.jsonl", "{}");
  Object.defineProperty(large, "size", { value: 21 * 1024 * 1024 });
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [large] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("超过20MB");
  fireEvent.change(screen.getByLabelText("选择单元JSONL文件"), {
    target: { files: [localFile("ok.jsonl", "{}")] },
  });
  fireEvent.change(screen.getByLabelText("原文索引JSON（可选）"), {
    target: { value: '{"d":true}' },
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "提交JSONL受控上传" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "每项必须为文档对象",
  );
});
