// Unit tests for the window's pure helpers (column layout, sorting, Alt-compare): node --test test/unit.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtDelta, layoutColumns, sortChars, statDeltas } from "../renderer/js/dom.js";

const ALL = ["legion", "class", "level", "server", "gs", "cp"];
const keys = (w) => Object.keys(layoutColumns(w, ALL).spans);

test("columns drop in order as the window narrows, and the name grows when wide", () => {
  assert.deepEqual(keys(900), ["name", "legion", "class", "level", "server", "gs", "cp"]);
  assert.ok(!keys(540).includes("server") && keys(540).includes("legion"));
  assert.deepEqual(keys(430), ["name", "class", "level", "gs", "cp"]);
  assert.deepEqual(keys(370), ["name", "level", "gs", "cp"]);
  const span = (w) => { const [a, b] = layoutColumns(w, ALL).spans.name; return b - a; };
  assert.ok(span(900) > span(600));
});

test("columns never overlap and stay left of the star", () => {
  for (let w = 300; w < 1400; w += 37) {
    const k = layoutColumns(w, ALL), spans = Object.values(k.spans);
    for (let i = 1; i < spans.length; i++) assert.ok(spans[i - 1][1] <= spans[i][0], `overlap at ${w}`);
    assert.ok(spans.at(-1)[1] <= k.star - 10, `under the star at ${w}`);
  }
});

const ch = (name, cp = null, level = 45) => ({ key: name, name, level, combat_power: cp });
const names = (l) => l.map((c) => c.name);

test("Recent: newest first, enemies grouped first, order kept without times", () => {
  const [a, b, c] = [ch("Ann"), ch("Bob"), ch("Cid")];
  const when = { Ann: 10, Bob: 30, Cid: 20 };
  assert.deepEqual(names(sortChars([a, b, c], "latest", false, null, when)), ["Bob", "Cid", "Ann"]);
  assert.deepEqual(names(sortChars([a, b, c], "latest", false, { Ann: "enemy", Bob: "ally", Cid: "enemy" }, when)), ["Cid", "Ann", "Bob"]);
  assert.deepEqual(names(sortChars([ch("Bob"), ch("Ann")], "latest", false, null, {})), ["Bob", "Ann"]);
});

test("columns sort both ways; unknown numbers always last", () => {
  const [a, b, c] = [ch("Ann", 5, 40), ch("bob", null, 45), ch("Cid", 9, 42)];
  assert.deepEqual(names(sortChars([c, b, a], "name")), ["Ann", "bob", "Cid"]);
  assert.deepEqual(names(sortChars([c, b, a], "name", true)), ["Cid", "bob", "Ann"]);
  assert.deepEqual(names(sortChars([a, b, c], "level")), ["bob", "Cid", "Ann"]);
  assert.deepEqual(names(sortChars([a, b, c], "cp")), ["Cid", "Ann", "bob"]);
  assert.deepEqual(names(sortChars([a, b, c], "cp", true)), ["Ann", "Cid", "bob"]);
  assert.deepEqual(names(sortChars([a, b, c], "cp", false, { Ann: "ally", bob: "enemy", Cid: "ally" })), ["bob", "Cid", "Ann"]);
});

test("Alt-compare: totals with exceed, item level, missing stats count as zero", () => {
  const theirs = { item_level: 320, main_stats: [["Attack", "442", "146"], ["Crit", "5%", ""]], exceed_stats: [["Attack", "24"]] };
  const mine = { item_level: 300, main_stats: [["Attack", "400", "100"], ["Crit", "5%", ""]] };
  const d = statDeltas(mine, theirs);
  assert.deepEqual(d.Attack, [112, false]);
  assert.deepEqual(d["Item Level"], [20, false]);
  assert.ok(!("Crit" in d));
  assert.deepEqual(statDeltas({}, { main_stats: [["Block", "200", ""]] }), { Block: [200, false] });
  assert.equal(fmtDelta(12), "▲12");
  assert.equal(fmtDelta(-3.5, true), "▼3.5%");
  assert.equal(fmtDelta(1500), "▲1,500");
});
