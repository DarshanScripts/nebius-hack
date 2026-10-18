import {createHash} from 'node:crypto';
import {createReadStream} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import type {ArtifactRef} from './types/contracts';

export const RENDERER_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const REPO_ROOT = path.resolve(RENDERER_DIR, '..');

/** ARTIFACT_ROOT; a relative value is resolved against the repository root (same as the Python side). */
export const artifactRoot = (): string => path.resolve(REPO_ROOT, process.env.ARTIFACT_ROOT ?? './output');

export class InputError extends Error {}

/** Resolve a relative artifact key inside ARTIFACT_ROOT, rejecting traversal/absolute keys. */
export const resolveKey = (key: string): string => {
  if (typeof key !== 'string' || key.length === 0 || key.includes('\0') || key.includes('\\')) {
    throw new InputError(`Invalid artifact key: ${JSON.stringify(key)}`);
  }
  if (path.isAbsolute(key) || /^[a-zA-Z]+:/.test(key) || key.split('/').some((p) => p === '..' || p === '')) {
    throw new InputError(`Artifact key must be relative without '..': ${key}`);
  }
  const root = artifactRoot();
  const full = path.resolve(root, key);
  if (full !== root && !full.startsWith(root + path.sep)) throw new InputError(`Artifact key escapes root: ${key}`);
  return full;
};

export const sha256File = (file: string): Promise<string> =>
  new Promise((resolve, reject) => {
    const h = createHash('sha256');
    createReadStream(file)
      .on('data', (d) => h.update(d))
      .on('error', reject)
      .on('end', () => resolve(h.digest('hex')));
  });

/** Verify an ArtifactRef exists inside the root (no symlink escape) and matches its hash/size. */
export const verifyRef = async (ref: ArtifactRef, label: string): Promise<string> => {
  const full = resolveKey(ref.key);
  let real: string;
  try {
    real = await fs.realpath(full);
  } catch {
    throw new InputError(`${label}: artifact missing: ${ref.key}`);
  }
  const rootReal = await fs.realpath(artifactRoot());
  if (!real.startsWith(rootReal + path.sep)) throw new InputError(`${label}: artifact resolves outside root: ${ref.key}`);
  const st = await fs.stat(real);
  if (st.size !== ref.size_bytes) throw new InputError(`${label}: size mismatch for ${ref.key} (${st.size} != ${ref.size_bytes})`);
  const sha = await sha256File(real);
  if (sha !== ref.sha256) throw new InputError(`${label}: sha256 mismatch for ${ref.key}`);
  return real;
};

/** Move a finished file into ARTIFACT_ROOT atomically (temp + rename) and describe it. */
export const publishFile = async (src: string, key: string, mediaType: string): Promise<ArtifactRef> => {
  const dest = resolveKey(key);
  await fs.mkdir(path.dirname(dest), {recursive: true});
  try {
    await fs.access(dest);
    throw new InputError(`Refusing to overwrite immutable artifact ${key}`);
  } catch (e) {
    if (e instanceof InputError) throw e;
  }
  const tmp = `${dest}.tmp-${process.pid}-${Date.now()}`;
  await fs.copyFile(src, tmp);
  await fs.rename(tmp, dest);
  const st = await fs.stat(dest);
  return {key, media_type: mediaType, sha256: await sha256File(dest), size_bytes: st.size};
};

export const writeJsonAtomic = async (key: string, value: unknown): Promise<void> => {
  const dest = resolveKey(key);
  await fs.mkdir(path.dirname(dest), {recursive: true});
  const tmp = `${dest}.tmp-${process.pid}-${Date.now()}`;
  await fs.writeFile(tmp, JSON.stringify(value, null, 2));
  await fs.rename(tmp, dest);
};

/** Canonical JSON (sorted keys, compact) for idempotency hashing. */
export const canonicalJson = (v: unknown): string => {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonicalJson).join(',')}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o)
    .sort()
    .filter((k) => o[k] !== undefined)
    .map((k) => `${JSON.stringify(k)}:${canonicalJson(o[k])}`)
    .join(',')}}`;
};

export const sha256Text = (s: string): string => createHash('sha256').update(s).digest('hex');
