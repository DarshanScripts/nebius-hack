// Generated scene source checks: a fast static policy check (imports,
// determinism, no network/secrets) plus a strict TypeScript type-check
// against the real scene kit. Run as a script it type-checks one file in an
// isolated temp dir and prints a SourceValidationResult as JSON.
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import ts from 'typescript';
import {RENDERER_DIR} from './artifacts';
import type {SourceValidationResult} from './types/contracts';

const ALLOWED_MODULES = new Set(['react', 'remotion', './scene-kit']);
const ALLOWED_REMOTION = new Set([
  'interpolate', 'interpolateColors', 'spring', 'Easing', 'AbsoluteFill', 'Sequence', 'Series',
  'useCurrentFrame', 'useVideoConfig', 'random', 'Freeze', 'Loop', 'measureSpring',
]);
const FORBIDDEN_REACT = new Set([
  'useState', 'useReducer', 'useEffect', 'useLayoutEffect', 'useInsertionEffect', 'useRef',
  'useTransition', 'startTransition', 'useSyncExternalStore', 'lazy', 'use',
]);
const FORBIDDEN_GLOBALS = new Set([
  'fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'setTimeout', 'setInterval', 'setImmediate',
  'requestAnimationFrame', 'requestIdleCallback', 'queueMicrotask', 'Date', 'performance', 'eval',
  'Function', 'process', 'require', 'globalThis', 'window', 'document', 'self', 'localStorage',
  'sessionStorage', 'indexedDB', 'navigator', 'location', 'importScripts', 'Worker', 'SharedWorker',
  'crypto', 'Image', 'Audio', 'FontFace', 'module', 'exports', '__dirname', '__filename',
]);
const FORBIDDEN_JSX = new Set(['img', 'video', 'audio', 'iframe', 'script', 'link', 'object', 'embed', 'image', 'foreignObject', 'style', 'source', 'track', 'use']);
const MIN_FONT_PX = 36;
const URLISH = /^\s*(https?:|file:|ftp:|wss?:|\/\/|blob:)/i;

const at = (sf: ts.SourceFile, node: ts.Node): string => {
  const {line, character} = sf.getLineAndCharacterOfPosition(node.getStart(sf));
  return `Scene.tsx:${line + 1}:${character + 1}`;
};

/** Policy check on the raw source. Returns diagnostics (empty = pass). */
export const staticCheck = (source: string): string[] => {
  const out: string[] = [];
  if (source.length > 200_000) return ['Scene.tsx: source exceeds 200000 characters'];
  const sf = ts.createSourceFile('Scene.tsx', source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TSX);
  let hasDefault = false;
  const reactNames = new Set<string>();

  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node)) {
      const mod = (node.moduleSpecifier as ts.StringLiteral).text;
      if (!ALLOWED_MODULES.has(mod)) out.push(`${at(sf, node)} import of '${mod}' is not allowed (allowed: react, remotion, ./scene-kit)`);
      const clause = node.importClause;
      if (clause?.name && mod === 'react') reactNames.add(clause.name.text);
      const nb = clause?.namedBindings;
      if (nb && ts.isNamespaceImport(nb)) {
        if (mod === 'react') reactNames.add(nb.name.text);
        else if (mod === 'remotion') out.push(`${at(sf, node)} namespace import of 'remotion' is not allowed; import named helpers`);
      }
      if (nb && ts.isNamedImports(nb)) {
        for (const el of nb.elements) {
          const name = (el.propertyName ?? el.name).text;
          if (mod === 'remotion' && !ALLOWED_REMOTION.has(name)) out.push(`${at(sf, el)} remotion '${name}' is not allowed in scenes (audio/media/assets are provided by the shell and scene-kit)`);
          if (mod === 'react' && FORBIDDEN_REACT.has(name)) out.push(`${at(sf, el)} React '${name}' is not allowed: scenes must be pure functions of the frame`);
        }
      }
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier) {
      out.push(`${at(sf, node)} re-exports from other modules are not allowed`);
    } else if (ts.isExportAssignment(node) && !node.isExportEquals) {
      hasDefault = true;
    } else if ((ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node)) && node.modifiers?.some((m) => m.kind === ts.SyntaxKind.DefaultKeyword)) {
      hasDefault = true;
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      out.push(`${at(sf, node)} dynamic import() is not allowed`);
    } else if (ts.isIdentifier(node) && FORBIDDEN_GLOBALS.has(node.text)) {
      const p = node.parent;
      const isPropName = (ts.isPropertyAccessExpression(p) && p.name === node) || (ts.isPropertyAssignment(p) && p.name === node) || ts.isJsxAttribute(p) || (ts.isMethodDeclaration(p) && p.name === node) || (ts.isPropertySignature(p) && p.name === node);
      if (!isPropName) out.push(`${at(sf, node)} '${node.text}' is not allowed (no timers, wall clock, network, globals or secrets)`);
    } else if (ts.isPropertyAccessExpression(node)) {
      const obj = node.expression;
      if (ts.isIdentifier(obj) && obj.text === 'Math' && node.name.text === 'random') out.push(`${at(sf, node)} Math.random is not allowed; use remotion random(seed)`);
      if (ts.isIdentifier(obj) && reactNames.has(obj.text) && FORBIDDEN_REACT.has(node.name.text)) out.push(`${at(sf, node)} React.${node.name.text} is not allowed`);
    } else if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(sf);
      if (FORBIDDEN_JSX.has(tag)) out.push(`${at(sf, node)} <${tag}> is not allowed; use scene-kit components (SceneImage, Icon, Svg)`);
      for (const attr of node.attributes.properties) {
        if (ts.isJsxAttribute(attr) && attr.name.getText(sf) === 'dangerouslySetInnerHTML') out.push(`${at(sf, attr)} dangerouslySetInnerHTML is not allowed`);
      }
    } else if ((ts.isPropertyAssignment(node) || ts.isJsxAttribute(node)) && ['fontSize', 'font-size'].includes(node.name.getText(sf).replace(/['"]/g, ''))) {
      // Theme rule: board text >= 36 px. Only literal sizes are checkable statically.
      let init: ts.Node | undefined = node.initializer;
      if (init && ts.isJsxExpression(init)) init = init.expression;
      const value = init && (ts.isNumericLiteral(init) || ts.isStringLiteral(init)) ? parseFloat(init.text) : NaN;
      if (!Number.isNaN(value) && value < MIN_FONT_PX) out.push(`${at(sf, node)} fontSize ${value} is below the ${MIN_FONT_PX}px minimum for board text`);
    } else if (ts.isStringLiteralLike(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      const text = node.text;
      if (URLISH.test(text) || /url\s*\(/i.test(text) || /@import/i.test(text)) out.push(`${at(sf, node)} external URL / CSS url() strings are not allowed`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  if (!hasDefault) out.push('Scene.tsx: missing `export default function Scene(props: SceneProps)`');
  for (const d of (sf as unknown as {parseDiagnostics?: ts.Diagnostic[]}).parseDiagnostics ?? []) {
    out.push(`Scene.tsx: syntax error: ${ts.flattenDiagnosticMessageText(d.messageText, '\n')}`);
  }
  return out;
};

const KIT_FILES = ['scene-kit.tsx', 'types/contracts.ts'];

/** Strict type-check of one scene module against the real kit in an isolated temp dir. */
export const typeCheck = async (source: string, workRoot = os.tmpdir()): Promise<string[]> => {
  const dir = path.join(workRoot, `validate-${randomUUID()}`);
  try {
    await fs.mkdir(path.join(dir, 'src', 'types'), {recursive: true});
    await fs.symlink(path.join(RENDERER_DIR, 'node_modules'), path.join(dir, 'node_modules'), 'dir');
    for (const f of KIT_FILES) await fs.copyFile(path.join(RENDERER_DIR, 'src', f), path.join(dir, 'src', f));
    const file = path.join(dir, 'src', 'Scene.tsx');
    await fs.writeFile(file, source);
    const program = ts.createProgram([file], {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      jsx: ts.JsxEmit.ReactJSX,
      strict: true,
      noEmit: true,
      skipLibCheck: true,
      esModuleInterop: true,
      types: [],
      lib: ['lib.es2022.d.ts', 'lib.dom.d.ts'],
    });
    const out = ts
      .getPreEmitDiagnostics(program)
      .filter((d) => !d.file || d.file.fileName === file)
      .map((d) => {
        const msg = ts.flattenDiagnosticMessageText(d.messageText, '\n');
        if (!d.file || d.start === undefined) return `Scene.tsx: ${msg}`;
        const {line, character} = d.file.getLineAndCharacterOfPosition(d.start);
        return `Scene.tsx:${line + 1}:${character + 1} TS${d.code}: ${msg}`;
      });
    const sf = program.getSourceFile(file);
    const sym = sf && program.getTypeChecker().getSymbolAtLocation(sf);
    const def = sym && program.getTypeChecker().getExportsOfModule(sym).find((s) => s.escapedName === 'default');
    if (!def) out.push('Scene.tsx: module has no default export');
    else {
      const checker = program.getTypeChecker();
      const t = checker.getTypeOfSymbolAtLocation(def, sf!);
      if (t.getCallSignatures().length === 0) out.push('Scene.tsx: default export must be a React function component');
    }
    return out;
  } finally {
    await fs.rm(dir, {recursive: true, force: true});
  }
};

export const validateSource = async (source: string, workRoot?: string): Promise<SourceValidationResult> => {
  const diagnostics = staticCheck(source);
  if (diagnostics.some((d) => d.includes('syntax error'))) return {valid: false, diagnostics};
  diagnostics.push(...(await typeCheck(source, workRoot)));
  return {valid: diagnostics.length === 0, diagnostics};
};

// CLI: tsx src/source-check.ts <file>  -> prints SourceValidationResult JSON.
if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  const file = process.argv[2];
  fs.readFile(file, 'utf8')
    .then((src) => validateSource(src, process.argv[3]))
    .then((r) => process.stdout.write(JSON.stringify(r) + '\n'))
    .catch((e) => {
      process.stdout.write(JSON.stringify({valid: false, diagnostics: [`validator error: ${String(e)}`]}) + '\n');
      process.exitCode = 1;
    });
}
