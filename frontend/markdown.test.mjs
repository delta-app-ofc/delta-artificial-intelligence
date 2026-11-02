import assert from 'node:assert/strict';
import test from 'node:test';
import { parseInline, parseMarkdown } from './markdown.js';

test('negrito, itálico e código em linha', () => {
  assert.deepEqual(parseInline('a **b** `c` _d_'), [
    { type: 'text', text: 'a ' }, { type: 'strong', text: 'b' }, { type: 'text', text: ' ' },
    { type: 'code', text: 'c' }, { type: 'text', text: ' ' }, { type: 'em', text: 'd' },
  ]);
});

test('texto com HTML continua texto', () => {
  const [part] = parseInline('<img src=x onerror=alert(1)>');
  assert.equal(part.type, 'text');
});

test('títulos, listas e parágrafos', () => {
  const blocks = parseMarkdown('## Título\n\nlinha 1\nlinha 2\n\n- um\n- dois\n\n1. a\n2. b');
  assert.deepEqual(blocks.map(b => b.type), ['h', 'p', 'list', 'list']);
  assert.deepEqual(blocks[1].lines, ['linha 1', 'linha 2']);
  assert.equal(blocks[2].ordered, false);
  assert.deepEqual(blocks[3].items, ['a', 'b']);
});

test('entrada vazia ou nula não quebra', () => {
  assert.deepEqual(parseMarkdown(''), []);
  assert.deepEqual(parseMarkdown(null), []);
});
