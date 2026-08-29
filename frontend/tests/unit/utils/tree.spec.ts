import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  extractPathList,
  deleteChildren,
  buildHierarchyTree,
  getNodeByUniqueId,
  appendFieldByUniqueId,
  handleTree
} from "@/utils/tree";

describe("utils/tree — extractPathList", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("空数组 → 返回空数组", () => {
    expect(extractPathList([])).toEqual([]);
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(extractPathList(null as any)).toEqual([]);
    expect(extractPathList("x" as any)).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("无 children 的简单树 → 返回 uniqueId 列表", () => {
    const tree = [{ uniqueId: "a" }, { uniqueId: "b" }, { uniqueId: "c" }];
    expect(extractPathList(tree)).toEqual(["a", "b", "c"]);
  });

  it("嵌套树：当前实现只返回顶层 uniqueId（递归结果未收集，是源码行为）", () => {
    // 注意：源码里 extractPathList 对子节点递归调用后丢弃返回值，
    // 所以嵌套树只展开最外层 uniqueId。这里把这个行为作为既定事实记录下来。
    const tree = [
      {
        uniqueId: "1",
        children: [
          { uniqueId: "1-1", children: [{ uniqueId: "1-1-1" }] },
          { uniqueId: "1-2" }
        ]
      },
      { uniqueId: "2" }
    ];
    expect(extractPathList(tree)).toEqual(["1", "2"]);
  });
});

describe("utils/tree — deleteChildren", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("空数组 → 返回空数组", () => {
    expect(deleteChildren([])).toEqual([]);
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(deleteChildren(undefined as any)).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("单子节点：删除 children 字段", () => {
    const tree = [
      {
        children: [{ x: 1 }]
      }
    ];
    const out = deleteChildren(tree);
    expect(out[0].children).toBeUndefined();
  });

  it("多子节点：保留 children", () => {
    const tree = [
      {
        children: [{ x: 1 }, { x: 2 }]
      }
    ];
    deleteChildren(tree);
    expect(tree[0].children).toHaveLength(2);
  });

  it("为节点写入 id / parentId / pathList / uniqueId", () => {
    const tree = [{ a: 1 }, { a: 2 }];
    const out = deleteChildren(tree);
    expect(out[0].id).toBe(0);
    expect(out[0].parentId).toBeNull();
    expect(out[0].pathList).toEqual([0]);
    expect(out[0].uniqueId).toBe(0);
    expect(out[1].id).toBe(1);
    expect(out[1].parentId).toBeNull();
    expect(out[1].uniqueId).toBe(1);
  });

  it("嵌套：子节点的 uniqueId 用 parentId-index 形式", () => {
    const tree = [
      {
        children: [{ x: 1 }, { x: 2 }]
      }
    ];
    const out = deleteChildren(tree);
    expect(out[0].uniqueId).toBe(0);
    expect(out[0].children[0].id).toBe(0);
    expect(out[0].children[0].parentId).toBe(0);
    expect(out[0].children[0].uniqueId).toBe("0-0");
    expect(out[0].children[1].uniqueId).toBe("0-1");
  });
});

describe("utils/tree — buildHierarchyTree", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(buildHierarchyTree(null as any)).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("递归设置 id / parentId / pathList", () => {
    const tree = [{ children: [{ x: 1 }, { x: 2 }] }];
    const out = buildHierarchyTree(tree);
    expect(out[0].id).toBe(0);
    expect(out[0].parentId).toBeNull();
    expect(out[0].pathList).toEqual([0]);
    expect(out[0].children[0].parentId).toBe(0);
    expect(out[0].children[0].pathList).toEqual([0, 0]);
    expect(out[0].children[1].pathList).toEqual([0, 1]);
  });

  it("不写入 uniqueId 字段", () => {
    const tree = [{ children: [{ x: 1 }] }];
    buildHierarchyTree(tree);
    expect(tree[0]).not.toHaveProperty("uniqueId");
    expect(tree[0].children[0]).not.toHaveProperty("uniqueId");
  });
});

describe("utils/tree — getNodeByUniqueId", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("空 → 返回空数组", () => {
    expect(getNodeByUniqueId([], "x")).toEqual([]);
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(getNodeByUniqueId("x" as any, "y")).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("根级匹配", () => {
    const tree = [{ uniqueId: "a", label: "A" }, { uniqueId: "b" }];
    expect(getNodeByUniqueId(tree, "a")).toEqual({ uniqueId: "a", label: "A" });
  });

  it("嵌套匹配", () => {
    const node = { uniqueId: "n1" };
    const tree = [{ uniqueId: "a", children: [node] }];
    expect(getNodeByUniqueId(tree, "n1")).toBe(node);
  });

  it("深嵌套（3 层）通过 BFS descent 找到", () => {
    const target = { uniqueId: "deep" };
    const tree = [
      {
        uniqueId: "root",
        children: [
          {
            uniqueId: "mid",
            children: [{ uniqueId: "x" }, target, { uniqueId: "y" }]
          }
        ]
      }
    ];
    expect(getNodeByUniqueId(tree, "deep")).toBe(target);
  });

  it("找不到 → 返回空数组", () => {
    const tree = [
      {
        uniqueId: "root",
        children: [{ uniqueId: "a" }]
      }
    ];
    expect(getNodeByUniqueId(tree, "missing")).toEqual([]);
  });
});

describe("utils/tree — appendFieldByUniqueId", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(appendFieldByUniqueId(null as any, "x", { a: 1 })).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("匹配节点追加字段，不改其他节点", () => {
    const tree = [
      { uniqueId: "a", v: 1 },
      { uniqueId: "b", v: 2 }
    ];
    appendFieldByUniqueId(tree, "b", { flag: true, label: "B" });
    expect(tree[0]).toEqual({ uniqueId: "a", v: 1 });
    expect(tree[1]).toEqual({ uniqueId: "b", v: 2, flag: true, label: "B" });
  });

  it("支持嵌套节点匹配", () => {
    const target = { uniqueId: "deep" };
    const tree = [
      {
        uniqueId: "root",
        children: [
          {
            uniqueId: "mid",
            children: [target]
          }
        ]
      }
    ];
    appendFieldByUniqueId(tree, "deep", { highlighted: true });
    expect(target).toEqual({ uniqueId: "deep", highlighted: true });
  });

  it("fields 不是 plain object 时不修改", () => {
    const tree = [{ uniqueId: "a" }];
    appendFieldByUniqueId(tree, "a", ["x", "y"] as any);
    expect(tree[0]).toEqual({ uniqueId: "a" });
  });
});

describe("utils/tree — handleTree", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("非数组 → 返回空数组并 warn", () => {
    expect(handleTree(null as any)).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("扁平列表构建成树形", () => {
    const flat = [
      { id: 1, parentId: 0, name: "root1" },
      { id: 2, parentId: 1, name: "child1" },
      { id: 3, parentId: 0, name: "root2" },
      { id: 4, parentId: 3, name: "child2" }
    ];
    const tree = handleTree(flat);
    expect(tree).toHaveLength(2);
    expect(tree[0].id).toBe(1);
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].id).toBe(2);
    expect(tree[1].id).toBe(3);
    expect(tree[1].children[0].id).toBe(4);
  });

  it("根节点 parentId 不存在 → 升级为顶层", () => {
    const flat = [
      { id: "x", parentId: null, name: "x" },
      { id: "y", parentId: "x", name: "y" }
    ];
    const tree = handleTree(flat);
    expect(tree).toHaveLength(1);
    expect(tree[0].id).toBe("x");
    expect(tree[0].children[0].id).toBe("y");
  });

  it("支持自定义字段名", () => {
    const flat = [
      { uuid: "1", pid: 0, label: "root" },
      { uuid: "2", pid: "1", label: "child" }
    ];
    const tree = handleTree(flat, "uuid", "pid");
    expect(tree).toHaveLength(1);
    expect(tree[0].uuid).toBe("1");
    expect(tree[0].children).toHaveLength(1);
    expect(tree[0].children[0].uuid).toBe("2");
  });

  it("自定义 children 字段名", () => {
    const flat = [
      { id: 1, parentId: 0 },
      { id: 2, parentId: 1 }
    ];
    const tree = handleTree(flat, "id", "parentId", "kids");
    expect(tree[0].kids).toHaveLength(1);
    expect(tree[0].kids[0].id).toBe(2);
  });
});