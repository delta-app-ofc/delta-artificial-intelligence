// Markdown mínimo para as respostas do Delta: títulos, listas, negrito, itálico e código.
// Monta o DOM com createElement/textContent, nunca com innerHTML, então o texto não executa HTML.

const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_)/;

export function parseInline(text) {
  return text.split(INLINE).filter(part => part !== '').map(part => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return { type: 'strong', text: part.slice(2, -2) };
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return { type: 'code', text: part.slice(1, -1) };
    if ((part.startsWith('*') && part.endsWith('*') && part.length > 2) || (part.startsWith('_') && part.endsWith('_') && part.length > 2)) {
      return { type: 'em', text: part.slice(1, -1) };
    }
    return { type: 'text', text: part };
  });
}

export function parseMarkdown(source) {
  const blocks = [];
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'p', lines: paragraph });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
  };
  String(source ?? '').replace(/\r\n/g, '\n').split('\n').forEach(raw => {
    const line = raw.trimEnd();
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*•]\s+(.+)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (!line.trim()) { flushParagraph(); flushList(); return; }
    if (heading) { flushParagraph(); flushList(); blocks.push({ type: 'h', level: heading[1].length, text: heading[2] }); return; }
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) { flushList(); list = { type: 'list', ordered, items: [] }; }
      list.items.push((bullet || numbered)[1]);
      return;
    }
    flushList();
    paragraph.push(line);
  });
  flushParagraph();
  flushList();
  return blocks;
}

function appendInline(parent, text) {
  parseInline(text).forEach(part => {
    if (part.type === 'text') { parent.append(document.createTextNode(part.text)); return; }
    const tag = { strong: 'strong', em: 'em', code: 'code' }[part.type];
    const node = document.createElement(tag);
    node.textContent = part.text;
    parent.append(node);
  });
}

export function renderMarkdown(target, source) {
  target.classList.add('markdown');
  parseMarkdown(source).forEach(block => {
    if (block.type === 'h') {
      const node = document.createElement(`h${Math.min(block.level + 2, 6)}`);
      appendInline(node, block.text);
      target.append(node);
    } else if (block.type === 'list') {
      const node = document.createElement(block.ordered ? 'ol' : 'ul');
      block.items.forEach(item => { const li = document.createElement('li'); appendInline(li, item); node.append(li); });
      target.append(node);
    } else {
      const node = document.createElement('p');
      block.lines.forEach((line, index) => {
        if (index) node.append(document.createElement('br'));
        appendInline(node, line);
      });
      target.append(node);
    }
  });
  return target;
}
