import { readFile, writeFile, mkdir } from "node:fs/promises";
import { instance } from "@viz-js/viz";

const roots = new URL("./diagrams/", import.meta.url);
const assets = new URL("./assets/", import.meta.url);
const viz = await instance();
await mkdir(assets, { recursive: true });
for (const name of ["pipeline", "retrieval", "retry"]) {
  const source = await readFile(new URL(name + ".dot", roots), "utf8");
  const svg = viz.renderString(source, { format: "svg", engine: "dot" });
  await writeFile(new URL(name + ".svg", assets), svg);
}
