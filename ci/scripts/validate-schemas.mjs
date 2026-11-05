// Checks the JSON Schema contracts under a folder (default: contracts/).
//
//  - every *.schema.json must compile (valid JSON Schema 2020-12, all $refs resolve)
//  - every schema's $id must be https://syncwave.local/<path>, so relative $refs work
//  - every examples/<name>.json must be valid against the sibling <name>.schema.json
//
// Usage: npm install --no-save ajv@8 ajv-formats@3 && node ci/scripts/validate-schemas.mjs [folder]
import { readFileSync, readdirSync, statSync } from "node:fs";
import { basename, dirname, join, relative, sep } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const root = process.argv[2] ?? "contracts";
const ID_BASE = "https://syncwave.local/";

const walk = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });

const toPosix = (path) => path.split(sep).join("/");
const files = walk(root).map(toPosix);
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);

let failures = 0;
const fail = (file, message) => {
  failures += 1;
  console.error(`FAIL ${file}: ${message}`);
};

const readJson = (file) => {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    fail(file, `not valid JSON (${error.message})`);
    return undefined;
  }
};

// Register every schema first, so cross-file $refs resolve in any order.
const schemas = new Map();
for (const file of files.filter((f) => f.endsWith(".schema.json"))) {
  const schema = readJson(file);
  if (!schema) continue;
  const expectedId = ID_BASE + toPosix(relative(".", file));
  if (schema.$id !== expectedId) {
    fail(file, `$id must be "${expectedId}"`);
    continue;
  }
  try {
    ajv.addSchema(schema);
    schemas.set(file, schema.$id);
  } catch (error) {
    fail(file, error.message);
  }
}

for (const [file, id] of schemas) {
  try {
    ajv.getSchema(id);
    console.log(`ok   ${file}`);
  } catch (error) {
    fail(file, error.message);
  }
}

for (const file of files.filter((f) => f.endsWith(".json") && basename(dirname(f)) === "examples")) {
  const schemaFile = toPosix(join(dirname(dirname(file)), basename(file, ".json") + ".schema.json"));
  const id = schemas.get(schemaFile);
  if (!id) {
    fail(file, `no matching schema ${schemaFile}`);
    continue;
  }
  const example = readJson(file);
  if (example === undefined) continue;
  const validate = ajv.getSchema(id);
  if (validate(example)) {
    console.log(`ok   ${file}`);
  } else {
    fail(file, ajv.errorsText(validate.errors));
  }
}

if (failures > 0) {
  console.error(`\n${failures} contract problem(s) found.`);
  process.exit(1);
}
console.log(`\nAll ${schemas.size} schema(s) and their examples are valid.`);
