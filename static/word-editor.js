'use strict';

const wordFonts = ['Arial', 'Calibri', 'Georgia', 'Times New Roman'];
const wordSizes = [0, 8, 9, 11, 14, 18, 24, 32];
const wordTags = {paragraph:'p', heading:'h4', subheading:'h5', quote:'blockquote'};
let wordRange, wordDrag, wordOutline = '';
let wordSearchQuery='', wordSearchIndex=-1;

function wordToolbar() {
    const command = (name, label, title = label) => {
        const toggle = /^(bold|italic|underline|strikeThrough|justify|insert.*List)/.test(name);
        return `<button type="button" data-word-cmd="${name}" ${toggle?'data-word-toggle aria-pressed="false"':''} title="${title}" aria-label="${title}">${label}</button>`;
    };
    return `<div class="word-ribbon" role="toolbar" aria-label="Formato del documento">
        <div class="word-ribbon-group">
          <select id="wordStyle" aria-label="Estilo de párrafo"><option value="p">Normal</option><option value="h4">Título</option><option value="h5">Subtítulo</option><option value="blockquote">Cita</option></select>
          <select id="wordFont" aria-label="Tipografía">${wordFonts.map(font=>`<option>${font}</option>`).join('')}</select>
          <select id="wordSize" aria-label="Tamaño de letra">${wordSizes.slice(1).map((size,i)=>`<option value="${i+1}" ${size===9?'selected':''}>${size} pt</option>`).join('')}</select>
        </div>
        <div class="word-ribbon-group">
          ${command('bold','<b>N</b>','Negrita')}${command('italic','<i>C</i>','Cursiva')}${command('underline','<u>S</u>','Subrayado')}${command('strikeThrough','<s>T</s>','Tachado')}
          <input id="wordColor" aria-label="Color de texto" title="Color de texto" type="color" value="#152d37">
        </div>
        <div class="word-ribbon-group">
          ${command('justifyLeft',desktopIcon('align-left'),'Alinear a la izquierda')}${command('justifyCenter',desktopIcon('align-center'),'Centrar')}${command('justifyRight',desktopIcon('align-right'),'Alinear a la derecha')}${command('justifyFull',desktopIcon('align-justify'),'Justificar')}
          ${command('insertUnorderedList','• Lista','Lista con viñetas')}${command('insertOrderedList','1. Lista','Lista numerada')}
        </div>
        <div class="word-ribbon-group">
          ${command('undo',desktopIcon('undo'),'Deshacer edición')}${command('redo',desktopIcon('redo'),'Rehacer edición')}
          <button id="wordBreak" type="button" title="Inserta un salto después del bloque seleccionado">Salto de página</button>
        </div>
    </div>`;
}

function wordRunHTML(run) {
    const style = [];
    if (wordFonts.includes(run.font)) style.push(`font-family:${run.font}`);
    if (wordSizes.includes(run.size) && run.size) style.push(`font-size:${run.size}pt`);
    if (/^[\da-f]{6}$/i.test(run.color)) style.push(`color:#${run.color}`);
    let html = esc(run.text).replaceAll('\n','<br>');
    for (const [key, tag] of [['bold','b'],['italic','i'],['underline','u'],['strike','s']]) {
        if (run[key]) html = `<${tag}>${html}</${tag}>`;
    }
    return style.length ? `<span style="${style.join(';')}">${html}</span>` : html;
}

function wordTextHTML(block) {
    if (!Array.isArray(block.paragraphs)) {
        const text = block.text === '[DESARROLLAR RESPUESTA]' && block.type === 'response_text' ? '' : block.text;
        return text ? text.split(/\n\s*\n/).map(line=>`<p>${esc(line).replaceAll('\n','<br>')}</p>`).join('') : '<p><br></p>';
    }
    let html = '', list = '';
    for (const item of block.paragraphs) {
        const nextList = item.kind === 'bullet' ? 'ul' : item.kind === 'number' ? 'ol' : '';
        if (nextList !== list) {
            if (list) html += `</${list}>`;
            if (nextList) html += `<${nextList}>`;
            list = nextList;
        }
        const tag = list ? 'li' : wordTags[item.kind] || 'p';
        const align = ['left','center','right','justify'].includes(item.align) ? ` style="text-align:${item.align}"` : '';
        html += `<${tag}${align}>${(item.runs||[]).map(wordRunHTML).join('') || '<br>'}</${tag}>`;
    }
    return html + (list ? `</${list}>` : '') || '<p><br></p>';
}

function wordVisual(block, item, number) {
    if (!item) return '';
    const id = esc(item.asset_id);
    const size = ['small','wide'].includes(item.word_size) ? item.word_size : 'normal';
    const table = item.type === 'table' && item.mode === 'editable' && item.rows?.length;
    const originalWidth = item.bbox?.length === 4 ? Math.round((item.bbox[2] - item.bbox[0]) * 4 / 3) : 0;
    const imageWidth = originalWidth > 0 && size !== 'wide' ? ` width="${Math.round(originalWidth * (size==='small' ? .65 : 1))}"` : '';
    const visual = table ? `<table aria-label="${esc(item.caption)}">${item.rows.map((row,i)=>`<tr>${row.map((cell,j)=>{
        const tag = i ? 'td' : 'th';
        return `<${tag} contenteditable="plaintext-only" tabindex="0" data-word-cell="${i}:${j}">${esc(cell)}</${tag}>`;
    }).join('')}</tr>`).join('')}</table>`
        : `<img draggable="false" loading="lazy"${imageWidth} src="/api/asset/${job}/${encodeURIComponent(item.file)}" alt="${esc(item.caption)}">`;
    return `<figure class="word-visual word-size-${size}" data-word-visual="${id}">
        <div class="word-visual-tools">
          <button draggable="true" data-word-drag title="Arrastrar elemento" aria-label="Arrastrar elemento">⠿</button>
          <strong>${item.type === 'table' ? 'Tabla' : 'Imagen'} <small>· Página ${item.page}</small></strong>
          <select data-word-size aria-label="Tamaño del elemento">${[['small','Compacto'],['normal','Original'],['wide','Ancho']].map(([key,label])=>`<option value="${key}" ${key===size?'selected':''}>${label}</option>`).join('')}</select>
          <select data-word-destination aria-label="Mover a otro numeral"><option value="">Mover a…</option>${data.points.map(p=>`<option value="${esc(p.requirement_id)}">Numeral ${p.number}${p.number===number?' (actual)':''}</option>`).join('')}</select>
          <button data-word-hide title="Alternar inclusión en Word">${item.include===false?'Incluir':'Excluir'}</button>
        </div>
        ${item.include===false?'<p class="word-excluded">Este elemento está excluido de la exportación.</p>':visual}
        <figcaption>${esc(item.caption)}</figcaption>
      </figure>`;
}

function renderWordBlock(block, point, assets) {
    const label = block.type === 'requirement_text' ? 'Requerimiento de la autoridad' : 'Respuesta';
    let body = '';
    if (['requirement_text','response_text'].includes(block.type)) {
        const response = block.type === 'response_text';
        body = `<div class="word-block-label">${label}</div><div class="word-text ${response?'word-answer':''}" role="textbox" aria-label="${label} · numeral ${point.number}" aria-multiline="true" contenteditable="true" spellcheck="true" data-word-text>${wordTextHTML(block)}</div>`;
    } else if (block.type === 'asset') {
        body = wordVisual(block, assets.get(block.asset_id), point.number);
    } else if (block.type === 'page_break') {
        body = '<div class="word-break"><span>Salto de página</span><button data-word-remove-break>Quitar</button></div>';
    }
    return `<div class="canonical-block" data-block="${esc(block.block_id)}" data-type="${esc(block.type)}">${body}</div>`;
}

function renderPreview() {
    wordRange = null;
    const wrap = $('#previewTab');
    const scroll = wrap.querySelector('.word-scroll')?.scrollTop || 0;
    const assets = new Map(data.assets.map(item=>[item.asset_id,item]));
    const points = new Map(data.points.map(point=>[point.requirement_id,point]));
    const sections = (data.document.sections||[]).filter(section=>points.has(section.requirement_id));
    const fields = data.metadata_validation.fields || {};
    const heading = fields.taxpayer_name?.valid ? fields.taxpayer_name.value : 'Expediente fiscal';
    wrap.innerHTML = `<div id="wordEditorWorkspace" class="word-workspace">
        <div class="word-desk-head"><div class="word-heading-cluster"><span data-word-company hidden></span><div><span class="eyebrow">Redacción del escrito</span><strong>Estudio Word</strong></div></div><div class="word-desk-actions"><button id="wordCraftBtn" class="primary" type="button">WordCraft profesional</button><button id="wordFullscreenBtn" class="icon-action" type="button">${desktopIcon('expand')} Enfoque</button><button id="v2Save" class="icon-action" type="button">${desktopIcon('save')} Guardar</button><button id="wordDownload" class="primary icon-action" type="button">${desktopIcon('download')} Descargar DOCX</button></div></div>
        ${wordToolbar()}
        <div class="word-outline"><label for="wordOutline">Ir al numeral</label><select id="wordOutline">${sections.map(s=>`<option value="${esc(s.requirement_id)}" ${s.requirement_id===wordOutline?'selected':''}>Numeral ${points.get(s.requirement_id).number}</option>`).join('')}</select>
          <button id="wordCompare" type="button">Comparar con original</button></div>
        <div class="word-find" role="search"><label for="wordFind">Buscar en Word</label><input id="wordFind" type="search" value="${esc(wordSearchQuery)}" placeholder="Texto, importe o anexo">
          <button id="wordFindPrev" type="button" aria-label="Coincidencia anterior">‹</button><button id="wordFindNext" type="button" aria-label="Siguiente coincidencia">›</button><output id="wordFindCount" aria-live="polite"></output></div>
        <div class="word-scroll"><article id="v2Document" class="word-sheet">
          <div class="word-letterhead"><span>Escrito de trabajo</span><span>${esc(validTemplateRfc(expedientRfc())?expedientRfc():'RFC pendiente')}</span></div>
          <h1>Contestación al<br>requerimiento</h1><p class="word-entity">${esc(heading)}</p>
          ${data.introduction?`<p class="word-intro">${esc(data.introduction)}</p>`:''}
          ${sections.map(s=>{const p=points.get(s.requirement_id);return `<section class="v2-section" data-rid="${esc(s.requirement_id)}"><header class="word-section-head"><span>Numeral</span><b>${String(p.number).padStart(2,'0')}</b></header>${s.blocks.filter(b=>b.type!=='support_list').map(b=>renderWordBlock(b,p,assets)).join('')}</section>`}).join('')}
        </article></div>
    </div>`;
    wrap.querySelector('.word-scroll').scrollTop = scroll;
    window.CompanyIdentity.mount(wrap.querySelector('[data-word-company]'),expedientRfc(),{registeredOnly:true});
    bindWordEditor(wrap);
}

function goWordNumeral(rid) {
    if(!rid)return;
    wordOutline=rid;
    const select=$('#wordOutline');
    if(select)select.value=rid;
    [...document.querySelectorAll('#v2Document .v2-section')].find(section=>section.dataset.rid===rid)?.scrollIntoView({block:'start'});
}

function bindWordReview(wrap,sheet){
    const input=wrap.querySelector('#wordFind'), count=wrap.querySelector('#wordFindCount');
    const previous=wrap.querySelector('#wordFindPrev'), next=wrap.querySelector('#wordFindNext');
    const normalize=value=>String(value).normalize('NFD').replace(/\p{Diacritic}/gu,'').toLocaleLowerCase('es-MX');
    function find(step=0,scroll=false){
        wordSearchQuery=input.value;
        const query=normalize(wordSearchQuery.trim());
        const matches=query?[...sheet.querySelectorAll('.canonical-block')].filter(el=>
            normalize([...el.querySelectorAll('[data-word-text],[data-word-cell],figcaption')]
                .map(node=>node.value??node.textContent).join(' ')).includes(query)):[];
        wordSearchIndex=matches.length?(Math.max(0,wordSearchIndex)+step+matches.length)%matches.length:-1;
        sheet.querySelector('.word-found')?.classList.remove('word-found');
        const match=matches[wordSearchIndex];
        if(match){
            match.classList.add('word-found');
            if(scroll){
                wordOutline=match.closest('.v2-section').dataset.rid;
                wrap.querySelector('#wordOutline').value=wordOutline;
                match.scrollIntoView({block:'center'});
            }
        }
        count.textContent=query?(matches.length?`${wordSearchIndex+1} / ${matches.length} bloques`:'Sin coincidencias'):'';
        previous.disabled=next.disabled=!matches.length;
    }
    input.oninput=()=>{wordSearchIndex=0;find(0,true)};
    input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();find(event.shiftKey?-1:1,true)}};
    previous.onclick=()=>find(-1,true);next.onclick=()=>find(1,true);
    sheet.addEventListener('input',()=>{if(input.value)find()});
    find();
    wrap.querySelector('#wordCompare').onclick=()=>{
        const rid=wrap.querySelector('#wordOutline').value;
        const point=data.points.find(item=>item.requirement_id===rid);
        if(!point)return;
        const dialog=$('#compareDialog');
        $('#compareTitle').textContent='Comparar numeral '+point.number;
        $('#compareState').textContent=point.original_text===point.text?'El texto coincide con el original.':'El texto tiene cambios respecto del original.';
        $('#compareOriginal').textContent=point.original_text||'Sin texto original.';
        $('#compareEdited').textContent=point.text||'Sin texto editado.';
        dialog.showModal();
    };

}

function wordParagraphs(root) {
    const result = [];
    let paragraph;
    function add(kind, align) {
        paragraph = {kind, runs:[]};
        if (['left','right','center','justify'].includes(align)) paragraph.align = align;
        result.push(paragraph);
    }
    function walk(node, format = {}, listKind = '') {
        if (node.nodeType === Node.TEXT_NODE || node.nodeName === 'BR') {
            if (!paragraph) add('paragraph');
            const text = node.nodeName === 'BR' ? '\n' : node.nodeValue;
            if (text) paragraph.runs.push({...format,text});
            return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE || ['SCRIPT','STYLE','IMG','IFRAME'].includes(node.nodeName)) return;
        const tag = node.nodeName, style = node.style;
        if (tag === 'UL' || tag === 'OL') {
            for (const child of node.children) walk(child,format,tag === 'OL'?'number':'bullet');
            paragraph = null;
            return;
        }
        const kind = ({P:'paragraph',DIV:'paragraph',H2:'heading',H3:'subheading',H4:'heading',H5:'subheading',BLOCKQUOTE:'quote',LI:listKind||'bullet'})[tag];
        if (kind) add(kind,style.textAlign||node.getAttribute('align'));
        const next = {...format};
        if (['B','STRONG'].includes(tag) || /^(bold|[6-9]00)$/.test(style.fontWeight)) next.bold = true;
        if (['I','EM'].includes(tag) || style.fontStyle === 'italic') next.italic = true;
        if (tag === 'U' || style.textDecorationLine.includes('underline')) next.underline = true;
        if (['S','STRIKE','DEL'].includes(tag) || style.textDecorationLine.includes('line-through')) next.strike = true;
        const font = (style.fontFamily || node.getAttribute('face') || '').split(',')[0].replace(/["']/g,'');
        if (wordFonts.includes(font)) next.font = font;
        const size = wordSizes[Number(node.getAttribute('size'))] || (style.fontSize.endsWith('pt') ? Number.parseFloat(style.fontSize) : 0);
        if (wordSizes.includes(size) && size) next.size = size;
        const color = style.color || node.getAttribute('color') || '';
        const rgb = color.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/);
        if (rgb) next.color = rgb.slice(1).map(n=>Number(n).toString(16).padStart(2,'0')).join('');
        else if (/^#[\da-f]{6}$/i.test(color)) next.color = color.slice(1);
        for (const child of node.childNodes) walk(child,next,listKind);
        if (kind) paragraph = null;
    }
    for (const node of root.childNodes) walk(node);
    for (const item of result) {
        if (item.runs.length === 1 && item.runs[0].text === '\n') item.runs = [];
    }
    return result;
}

const wordPlainText = paragraphs => paragraphs.map(p=>p.runs.map(run=>run.text).join('')).join('\n\n').trim();

function migrateWordEditor() {
    if (!data.editor_state?.html) return;
    const legacy = new DOMParser().parseFromString(data.editor_state.html,'text/html');
    const nodes = new Map([...legacy.querySelectorAll('[data-block]')].map(el=>[el.dataset.block,el]));
    const squash = value => (value||'').trim().replace(/\s+/g,' ');
    for (const section of data.document.sections||[]) {
        for (const block of section.blocks) {
            const node = nodes.get(block.block_id);
            const root = node?.querySelector('.v2-point-text,.v2-response-text');
            const visual = node?.querySelector('.v2-asset');
            if (block.type==='asset' && visual) {
                const item = asset(block.asset_id);
                if (item && !item.word_size && visual.dataset.asset===item.asset_id) {
                    if (visual.classList.contains('asset-small')) item.word_size='small';
                    if (visual.classList.contains('asset-large')) item.word_size='wide';
                }
            }
            if (!root || block.paragraphs || block.text === '[DESARROLLAR RESPUESTA]') continue;
            const paragraphs = wordParagraphs(root);
            const formatted = paragraphs.some(p=>p.kind!=='paragraph'||p.align||p.runs.some(run=>Object.keys(run).length>1));
            if (formatted && squash(wordPlainText(paragraphs)) === squash(block.text)) block.paragraphs = paragraphs;
        }
    }
}

function wordBlockFor(el) {
    const section = data.document.sections.find(s=>s.requirement_id===el.closest('.v2-section')?.dataset.rid);
    const block = section?.blocks.find(b=>b.block_id===el.closest('[data-block]')?.dataset.block);
    return {section,block};
}

function commitWordText(el) {
    const {block} = wordBlockFor(el);
    if (!block) return;
    const paragraphs = wordParagraphs(el);
    const text = wordPlainText(paragraphs);
    if (text === block.text && JSON.stringify(paragraphs) === JSON.stringify(block.paragraphs)) return;
    block.text = text;
    block.paragraphs = paragraphs;
    const point = data.points.find(p=>p.requirement_id===el.closest('.v2-section').dataset.rid);
    if (block.type === 'requirement_text') {
        if(point.text!==text)point.status='review';
        point.text = text;
    }
    else point.response_text = text;
    markDirty();
}

function moveWordBlock(block, from, to, before) {
    if (!block || !to || block===before) return;
    snapshot();
    from.blocks.splice(from.blocks.indexOf(block),1);
    const index = before ? to.blocks.indexOf(before) : to.blocks.findIndex(b=>b.type==='response_text');
    to.blocks.splice(index < 0 ? to.blocks.length : index,0,block);
    for (const section of new Set([from,to])) {
        const point = data.points.find(p=>p.requirement_id===section.requirement_id);
        if (point) point.asset_ids = section.blocks.filter(item=>item.type==='asset').map(item=>item.asset_id);
    }
    markDirty();
    renderPreview();
    toast('Elemento reubicado');
}

function bindWordEditor(wrap) {
    const sheet = wrap.querySelector('#v2Document');
    function rememberSelection() {
        const selection = window.getSelection();
        const node = selection?.anchorNode;
        const element = node?.nodeType === Node.TEXT_NODE ? node.parentElement : node;
        const editable = element?.closest('[data-word-text]');
        if (editable && sheet.contains(editable) && editable.contains(selection.focusNode)) {
            wordRange = selection.getRangeAt(0).cloneRange();
            wordOutline=editable.closest('.v2-section').dataset.rid;
            wrap.querySelector('#wordOutline').value=wordOutline;
            for (const button of wrap.querySelectorAll('[data-word-toggle]')) {
                button.setAttribute('aria-pressed',document.queryCommandState(button.dataset.wordCmd));
            }
        }
    }
    sheet.onfocusin = rememberSelection;
    sheet.onkeyup = rememberSelection;
    sheet.onpointerup = rememberSelection;
    function format(command,value=null) {
        const anchor = wordRange?.startContainer;
        const editable = (anchor?.parentElement || anchor)?.closest?.('[data-word-text]');
        if (!editable || !sheet.contains(editable)) return toast('Selecciona texto o coloca el cursor en el escrito.','warn');
        editable.focus();
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(wordRange);
        document.execCommand(command,false,value);
        commitWordText(editable);
        rememberSelection();
    }
    wrap.querySelectorAll('[data-word-cmd]').forEach(button=>{
        button.onpointerdown = event=>event.preventDefault();
        button.onclick = ()=>format(button.dataset.wordCmd);
    });
    for (const [id,command] of [['wordFont','fontName'],['wordSize','fontSize'],['wordColor','foreColor'],['wordStyle','formatBlock']]) {
        wrap.querySelector('#'+id).onchange = event=>format(command,event.target.value);
    }
    sheet.oninput = event=>{
        const el = event.target, {block} = wordBlockFor(el);
        if (el.matches('[data-word-text]')) commitWordText(el);
        if (el.matches('[data-word-cell]')) {
            const [row,col] = el.dataset.wordCell.split(':').map(Number);
            asset(block.asset_id).rows[row][col] = el.innerText;
            markDirty();
        }
    };
    sheet.onpaste = event=>{
        if (!event.target.closest('[data-word-text]')) return;
        event.preventDefault();
        document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));
    };
    sheet.onchange = event=>{
        const el = event.target, {section,block} = wordBlockFor(el);
        if (el.matches('[data-word-size]')) {
            snapshot();
            asset(block.asset_id).word_size = el.value;
            markDirty();
            renderPreview();
        }
        if (el.matches('[data-word-destination]') && el.value) {
            moveWordBlock(block,section,data.document.sections.find(s=>s.requirement_id===el.value));
        }
    };
    sheet.onclick = event=>{
        const button = event.target.closest('[data-word-hide],[data-word-remove-break]');
        if (!button) return;
        const {section,block} = wordBlockFor(button);
        snapshot();
        if (button.matches('[data-word-hide]')) {
            const item = asset(block.asset_id);
            item.include = item.include === false;
            renderVisuals();
        } else section.blocks.splice(section.blocks.indexOf(block),1);
        markDirty();
        renderPreview();
    };
    sheet.ondragstart = event=>{
        const handle = event.target.closest('[data-word-drag]');
        if (!handle) return;
        wordDrag = wordBlockFor(handle);
        event.dataTransfer.setData('text/plain',wordDrag.block.block_id);
        event.dataTransfer.effectAllowed = 'move';
    };
    sheet.ondragover = event=>{
        const target = event.target.closest('.canonical-block');
        if (!wordDrag || !target) return;
        event.preventDefault();
        sheet.querySelector('.word-drop')?.classList.remove('word-drop');
        target.classList.add('word-drop');
    };
    sheet.ondragend = ()=>{
        wordDrag = null;
        sheet.querySelector('.word-drop')?.classList.remove('word-drop');
    };
    sheet.ondrop = event=>{
        if (!wordDrag) return;
        event.preventDefault();
        const {section,block} = wordBlockFor(event.target);
        if (block?.type !== 'requirement_text') moveWordBlock(wordDrag.block,wordDrag.section,section,block);
        sheet.ondragend();
    };
    wrap.querySelector('#wordOutline').onchange = event=>{
        goWordNumeral(event.target.value);
    };
    wrap.querySelector('#wordBreak').onclick = ()=>{
        const anchor = wordRange?.startContainer;
        const element = anchor?.nodeType === Node.TEXT_NODE ? anchor.parentElement : anchor;
        const {section,block} = element ? wordBlockFor(element) : {};
        if (!block) return toast('Coloca el cursor en el bloque que debe quedar antes del salto.','warn');
        snapshot();
        section.blocks.splice(section.blocks.indexOf(block)+1,0,{type:'page_break',block_id:`BREAK-${crypto.randomUUID()}`,version:1});
        markDirty();
        renderPreview();
    };
    wrap.querySelector('#wordFullscreenBtn').onclick = ()=>{
        $('#split').classList.toggle('max-right');
        $('#split').classList.remove('max-left');
        syncPaneControls();
    };
    wrap.querySelector('#v2Save').onclick = ()=>save();
    wrap.querySelector('#wordDownload').onclick = openExport;
    wrap.querySelector('#wordCraftBtn').onclick = openProfessionalWord;
    bindWordReview(wrap,sheet);
}
