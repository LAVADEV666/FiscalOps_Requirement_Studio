'use strict';

function openTemplateEditor(item) {
    const dialog = document.createElement('dialog');
    dialog.className = 'template-studio';
    dialog.setAttribute('aria-label', 'Editor de plantilla Word');
    document.body.append(dialog);
    dialog.addEventListener('close', () => dialog.remove(), {once: true});
    const url = templateUrl(item.rfc) + '/' + item.id;

    function draw(savedMessage = '') {
        dialog.innerHTML = `
            <header class="template-studio-head">
                <div class="template-title-cluster"><span data-template-company-avatar hidden></span><div><span>EDITOR DE PLANTILLAS · DOCX</span><h2></h2><small></small></div></div>
                <button type="button" class="icon-action" data-close>${desktopIcon('close')} Cerrar</button>
            </header>
            <div class="template-ribbon" role="group" aria-label="Herramientas de la plantilla">
                <div class="template-ribbon-group">
                    <span>ARCHIVO</span>
                    <a data-download download>${desktopIcon('download')} Descargar DOCX</a>
                    <button type="button" data-professional>Diseñar en WordCraft</button>
                    <button type="button" data-preview>Vista previa</button>
                    <label class="template-file-action">${desktopIcon('upload')} Sustituir DOCX<input type="file" accept=".docx" data-replace></label>
                </div>
                <div class="template-ribbon-group">
                    <span>FORMATO DE PÁRRAFO</span>
                    <button type="button" data-format="bold" aria-label="Negrita" title="Negrita"><b>N</b></button>
                    <button type="button" data-format="italic" aria-label="Cursiva" title="Cursiva"><i>C</i></button>
                    <button type="button" data-format="underline" aria-label="Subrayado" title="Subrayado"><u>S</u></button>
                    <select data-size aria-label="Tamaño de letra"></select>
                    <select data-align aria-label="Alineación"><option value="left">Izquierda</option><option value="center">Centro</option><option value="right">Derecha</option><option value="justify">Justificar</option></select>
                </div>
                <div class="template-ribbon-group">
                    <span>INSERTAR</span>
                    <button type="button" class="soft-button" data-insert aria-pressed="false">${desktopIcon('insert')} Colocar rectángulo OCR</button>
                    <label><input type="checkbox" data-ocr-frame> Borde del rectángulo en la plantilla</label>
                </div>
            </div>
            <div class="template-canvas">
                <div class="template-paper">
                    <div data-header></div>
                    <div data-body></div>
                    <div data-footer></div>
                </div>
            </div>
            <footer class="template-studio-foot">
                <p role="status"></p>
                <button type="button" class="primary icon-action" data-save>${desktopIcon('save')} Guardar plantilla</button>
            </footer>`;
        const find = selector => dialog.querySelector(selector);
        const status = find('[role=status]'), body = find('[data-body]');
        const insert = find('[data-insert]'), size = find('[data-size]'), align = find('[data-align]');
        const save = find('[data-save]'), replace = find('[data-replace]');
        const ocrFrame = find('[data-ocr-frame]');
        ocrFrame.checked = !!item.ocr_frame;
        const fields = new Map(item.fields.map(field => [field.id, field]));
        const inputs = new Map(), formatting = new Map();
        const toggles = [...dialog.querySelectorAll('[data-format]')];
        const sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48];
        let active, position = item.position, placing = false, busy = false;
        const defaultStatus = 'Coloca el rectángulo OCR donde irá el requerimiento. WordCraft permite agregar párrafos, tablas, imágenes y editar el diseño completo.';
        find('h2').textContent = item.name;
        window.CompanyIdentity.mount(find('[data-template-company-avatar]'), item.rfc, {registeredOnly:true});
        find('.template-studio-head small').textContent = item.rfc;
        find('[data-download]').href = url + '/file';
        status.textContent = savedMessage || defaultStatus;
        const currentFormat = id => ({...fields.get(id).format, ...formatting.get(id)});
        const plainText = input => input.value.replace(/[\r\n\t]/g, ' ');
        const changedTexts = () => Object.fromEntries([...inputs]
            .filter(([, input]) => input.value !== input.defaultValue)
            .map(([id, input]) => [id, plainText(input)]));
        const dirty = () => position !== item.position || ocrFrame.checked !== !!item.ocr_frame || formatting.size || Object.keys(changedTexts()).length;

        function paint(input, format) {
            input.style.fontWeight = format.bold ? '700' : '';
            input.style.fontStyle = format.italic ? 'italic' : '';
            input.style.textDecoration = format.underline ? 'underline' : '';
            input.style.fontSize = format.size + 'pt';
            input.style.textAlign = format.align;
        }

        function syncToolbar() {
            const format = active ? currentFormat(active) : {};
            for (const button of toggles) {
                button.disabled = !active;
                button.setAttribute('aria-pressed', String(!!format[button.dataset.format]));
            }
            size.replaceChildren(...sizes.map(value => new Option(value + ' pt', value)));
            if (active && !sizes.includes(format.size)) size.add(new Option(format.size + ' pt', format.size));
            size.value = active ? format.size : 11;
            align.value = format.align || 'left';
            size.disabled = align.disabled = !active;
        }

        function setFormat(key, value) {
            if (!active) return;
            const changes = {...formatting.get(active)};
            if (value === fields.get(active).format[key]) delete changes[key];
            else changes[key] = value;
            if (Object.keys(changes).length) formatting.set(active, changes);
            else formatting.delete(active);
            paint(inputs.get(active), currentFormat(active));
            syncToolbar();
        }

        function addField(parent, id, label) {
            const input = document.createElement('textarea');
            input.rows = 1;
            input.maxLength = 12000;
            input.defaultValue = fields.get(id).text;
            input.placeholder = 'Escribe aquí…';
            input.setAttribute('aria-label', label);
            paint(input, fields.get(id).format);
            input.onfocus = () => {
                inputs.get(active)?.classList.remove('selected');
                active = id;
                input.classList.add('selected');
                syncToolbar();
            };
            inputs.set(id, input);
            parent.append(input);
        }

        for (const [region, group] of [['header', 'Encabezado'], ['footer', 'Pie de página']]) {
            const groupFields = item.fields.filter(field => field.group === group);
            const target = find('[data-' + region + ']');
            target.hidden = !groupFields.length;
            if (!groupFields.length) continue;
            const heading = document.createElement('div');
            heading.className = 'template-paper-label';
            heading.textContent = group;
            target.append(heading);
            groupFields.forEach((field, index) => addField(target, field.id, group + ' ' + (index + 1)));
        }

        const marker = document.createElement('div');
        marker.className = 'template-marker';
        marker.innerHTML = `<div><strong>▧ CONTENIDO OCR</strong><br><code>{{REQUERIMIENTO}}</code><small>Aquí se insertarán los numerales, tablas e imágenes de Estudio Word. El bloque crece con el contenido.</small></div>
            <div><button type="button" aria-label="Subir bloque" title="Subir bloque">↑</button><button type="button" aria-label="Bajar bloque" title="Bajar bloque">↓</button></div>`;
        const [up, down] = marker.querySelectorAll('button');
        const gaps = [];
        for (let index = 0; index <= item.layout.length; index++) {
            const gap = document.createElement('div');
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = '⊕ Insertar aquí';
            button.setAttribute('aria-label', index < item.layout.length ? 'Insertar antes del bloque ' + (index + 1) : 'Insertar al final');
            button.onclick = () => {
                move(index);
                insert.focus();
            };
            gap.append(button);
            gap.className = 'template-gap';
            gaps.push(gap);
            body.append(gap);
            if (index === item.layout.length) break;
            const block = item.layout[index];
            const row = document.createElement('div');
            row.className = 'template-paper-block';
            if (block.kind !== 'paragraph' || !block.fields.length) {
                const label = document.createElement('div');
                label.className = 'template-paper-label';
                label.textContent = ({table:'Tabla', visual:'Elemento visual', paragraph:'Bloque de Word'})[block.kind];
                row.classList.add('structured');
                row.append(label);
                if (!block.fields.length) row.append(item.blocks[index]);
            }
            block.fields.forEach((id, i) => addField(row, id, 'Bloque ' + (index + 1) + (block.fields.length > 1 ? ', texto ' + (i + 1) : '')));
            body.append(row);
        }
        function togglePlacing(value) {
            placing = value;
            body.classList.toggle('placing', value);
            insert.setAttribute('aria-pressed', String(value));
            status.textContent = value ? 'Elige «Insertar aquí» en el punto donde irá el requerimiento.' : defaultStatus;
        }
        function move(next) {
            position = next;
            marker.classList.remove('is-positioned');
            gaps[position].after(marker);
            marker.classList.add('is-positioned');
            up.disabled = position === 0;
            down.disabled = position === gaps.length - 1;
            if (placing) togglePlacing(false);
            status.textContent = 'Punto de inserción actualizado. Guarda la plantilla para aplicarlo.';
        }
        gaps[position].after(marker);
        up.disabled = position === 0;
        down.disabled = position === gaps.length - 1;
        up.onclick = () => { move(position - 1); (up.disabled ? down : up).focus(); };
        down.onclick = () => { move(position + 1); (down.disabled ? up : down).focus(); };
        insert.onclick = () => togglePlacing(!placing);
        toggles.forEach(button => button.onclick = () => setFormat(button.dataset.format, button.getAttribute('aria-pressed') !== 'true'));
        size.onchange = () => setFormat('size', Number(size.value));
        align.onchange = () => setFormat('align', align.value);
        syncToolbar();

        async function submit(action, message) {
            if (busy) return;
            busy = true;
            save.setAttribute('aria-busy','true');
            const controls = [...dialog.querySelectorAll('button, input, textarea, select')].filter(control => !control.disabled);
            controls.forEach(control => control.disabled = true);
            status.textContent = 'Guardando plantilla…';
            try {
                item = await action();
                draw(message);
                dialog.querySelector('[data-save]').focus();
            } catch (error) {
                status.textContent = error.message;
            } finally {
                busy = false;
                save.removeAttribute('aria-busy');
                controls.forEach(control => control.disabled = false);
            }
        }
        save.onclick = () => {
            if (!dirty()) {
                status.textContent = 'La plantilla ya está guardada.';
                return;
            }
            const payload = {position, revision: item.revision, fields: changedTexts(), formatting: Object.fromEntries(formatting), ocr_frame:ocrFrame.checked};
            submit(() => templateRequest(url, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}), 'Plantilla guardada.');
        };
        dialog.onkeydown = event => {
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
                event.preventDefault();
                save.click();
            }
        };
        replace.onchange = () => {
            const file = replace.files[0];
            replace.value = '';
            if (!file || (dirty() && !confirm('¿Descartar los cambios y sustituir el DOCX?'))) return;
            const form = new FormData();
            form.set('file', file);
            form.set('revision', item.revision);
            submit(() => templateRequest(url + '/file', {method:'PUT', body:form}), 'DOCX sustituido. Revisa el punto de inserción.');
        };
        find('[data-download]').onclick = event => {
            if (!busy && !dirty()) return;
            event.preventDefault();
            if (!busy) status.textContent = 'Guarda los cambios antes de descargar el DOCX.';
        };
        find('[data-preview]').onclick = () => {
            if (dirty()) { status.textContent = 'Guarda los cambios para ver la plantilla actualizada.'; return; }
            previewTemplate(item.rfc, item.id);
        };
        find('[data-professional]').onclick = async () => {
            if (dirty()) { status.textContent = 'Guarda los cambios antes de abrir WordCraft.'; return; }
            const changed = await editTemplateInWordCraft(item);
            if (changed) {
                try { item = await templateRequest(url); draw('Diseño actualizado desde WordCraft.'); }
                catch (error) { status.textContent = error.message; }
            }
        };
        const mayClose = () => !busy && (!dirty() || confirm('¿Cerrar el editor y descartar los cambios sin guardar?'));
        dialog.oncancel = event => {
            if (placing) {
                event.preventDefault();
                togglePlacing(false);
                insert.focus();
            } else if (!mayClose()) event.preventDefault();
        };
        find('[data-close]').onclick = () => { if (mayClose()) dialog.close(); };
    }

    draw();
    dialog.showModal();
}
