'use strict';

// WordCraft 0.14.0's official, same-origin host=parent protocol.
let retainedWordCraft;
function openWordCraft({title, name, load, save, onSaved, downloadUrl, needsSave = false, forceNew = false, companyRfc = ''}) {
    if (retainedWordCraft) {
        if ((!forceNew && retainedWordCraft.title === title) || retainedWordCraft.hasPending()) {
            if (retainedWordCraft.title !== title || forceNew) retainedWordCraft.notify('Tu otro documento tiene cambios pendientes. Guárdalo antes de abrir uno nuevo.');
            return retainedWordCraft.resume();
        }
        retainedWordCraft.dispose();
    }
    const dialog = document.createElement('dialog');
    dialog.className = 'wordcraft-studio';
    dialog.setAttribute('aria-label', title);
    dialog.innerHTML = `<header class="template-studio-head"><div class="wordcraft-title"><img src="/static/ssgt-logo.png" alt="Salles Sainz Grant Thornton">${ssgtSymbolHTML()}<span data-wordcraft-company hidden></span><div><span>WORDCRAFT · POWERED BY FISCALOPS</span><h2></h2></div></div><div class="template-card-actions"><a data-download download>Descargar DOCX</a><button type="button" data-close>← Volver al editor</button></div></header>
        <div class="wordcraft-status"><p role="status">Iniciando WordCraft local…</p><button type="button" data-retry hidden>Reintentar guardado</button><button type="button" data-recover hidden>Descargar copia de recuperación</button></div>
        <div class="wordcraft-frame"><iframe title="Editor profesional WordCraft" allow="fullscreen; clipboard-read; clipboard-write" allowfullscreen></iframe><div class="wordcraft-loading"><div class="engine-loader"><span class="engine-orbit"></span>${ssgtSymbolHTML()}</div><strong>Iniciando WordCraft</strong><small>SSGT · Powered by FiscalOps</small></div></div>`;
    dialog.querySelector('h2').textContent = title;
    document.body.append(dialog);
    window.CompanyIdentity.mount(dialog.querySelector('[data-wordcraft-company]'), companyRfc, {registeredOnly:true});
    const finishLoadingMotion = window.FiscalMotion.begin();
    const finishLoading = () => { finishLoadingMotion(); dialog.querySelector('.wordcraft-loading').hidden = true; };
    const frame = dialog.querySelector('iframe'), status = dialog.querySelector('[role=status]');
    const recover = dialog.querySelector('[data-recover]');
    const retry = dialog.querySelector('[data-retry]');
    const downloadLink = dialog.querySelector('[data-download]');
    downloadLink.hidden = !downloadUrl;
    if (downloadUrl) downloadLink.href = downloadUrl;
    let dirty = false, pending = null, saving = false, lastBytes = null, loaded = false, changed = false;
    let returnWaiters = [], disposed = false;
    const waitToReturn = () => new Promise(resolve => returnWaiters.push(resolve));
    const closed = waitToReturn();
    const resumeButton = document.createElement('button');
    resumeButton.className = 'wordcraft-resume';
    resumeButton.type = 'button';
    resumeButton.hidden = true;
    document.body.append(resumeButton);
    function placeResume() {
        if (disposed || dialog.open || resumeButton.hidden) return;
        const host = [...document.querySelectorAll('dialog[open]')].filter(node=>node!==dialog).at(-1) || document.body;
        const container = host === document.body ? host : host.querySelector('footer') || host;
        resumeButton.classList.toggle('in-dialog', host !== document.body);
        if (resumeButton.parentElement !== container) container.append(resumeButton);
    }
    const resumeObserver = new MutationObserver(placeResume);
    resumeObserver.observe(document.body, {childList:true, subtree:true, attributes:true, attributeFilter:['open']});
    function updateResume() {
        resumeButton.textContent = (dirty || pending || saving ? '● ' : '') + 'Retomar WordCraft' + (dirty || pending ? ' · cambios pendientes' : '');
    }
    const session = {
        title,
        notify: text => status.textContent = text,
        hasPending: () => !!(dirty || pending || saving),
        resume: () => {
            const promise = waitToReturn();
            resumeButton.hidden = true;
            if (!dialog.open) dialog.showModal();
            return promise;
        },
        dispose: () => {
            disposed = true;
            resumeObserver.disconnect();
            finishLoading();
            window.removeEventListener('message', message);
            window.removeEventListener('beforeunload', beforeUnload);
            dialog.remove(); resumeButton.remove();
            returnWaiters.splice(0).forEach(resolve=>resolve(changed));
            if (retainedWordCraft === session) retainedWordCraft = null;
        }
    };
    retainedWordCraft = session;
    resumeButton.onclick = () => session.resume();
    const download = (bytes, filename) => {
        const url = URL.createObjectURL(new Blob([bytes]));
        const link = document.createElement('a');
        link.href = url; link.download = filename; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    recover.onclick = () => { if (lastBytes) download(lastBytes, 'Recuperacion_' + name); };
    downloadLink.onclick = event => {
        if (!loaded || needsSave || dirty || pending || saving) {
            event.preventDefault();
            status.textContent = 'Guarda con Ctrl+S antes de descargar el DOCX.';
        }
    };
    async function flush() {
        if (saving || !pending) return;
        saving = true;
        retry.hidden = true;
        while (pending) {
            const current = pending;
            pending = null;
            status.textContent = 'Guardando DOCX en FiscalOps…';
            try {
                await save(current);
                needsSave = false;
                recover.hidden = true;
                changed = true;
                status.textContent = 'DOCX guardado en FiscalOps. Usa Ctrl+S para guardar nuevas ediciones.';
            } catch (error) {
                // WordCraft considers postMessage a completed save; retain the bytes ourselves.
                if (!pending) pending = current;
                status.textContent = error.message + ' Tus cambios siguen disponibles en la copia de recuperación. Puedes reintentar el guardado.';
                recover.hidden = false;
                retry.hidden = false;
                break;
            }
        }
        saving = false;
        updateResume();
    }
    retry.onclick = flush;
    async function message(event) {
        if (event.origin !== location.origin || event.source !== frame.contentWindow || !event.data) return;
        const value = event.data;
        if (value.type === 'wordcraft:ready' && !loaded) {
            loaded = true;
            try {
                const bytes = await load();
                if (!dialog.isConnected) return;
                frame.contentWindow.postMessage({type:'wordcraft:open', name, bytes}, location.origin, [bytes]);
                status.textContent = 'Edita tu documento y usa Ctrl+S o Archivo → Guardar para conservarlo en FiscalOps.';
            } catch (error) { status.textContent = error.message; }
            finally { finishLoading(); }
        } else if (value.type === 'wordcraft:dirty') {
            dirty = !!value.dirty;
            if (dirty && !saving) status.textContent = 'Cambios sin guardar. Usa Ctrl+S o Archivo → Guardar.';
            updateResume();
        } else if (value.type === 'wordcraft:failed') {
            finishLoading();
            status.textContent = 'WordCraft no pudo iniciar: ' + String(value.error || 'WebGL2 no disponible.');
        } else if (value.type === 'wordcraft:save' && (value.bytes instanceof ArrayBuffer || value.bytes instanceof Uint8Array)) {
            const filename = String(value.name || name).split(/[\\/]/).pop();
            if (!filename.toLowerCase().endsWith('.docx')) {
                download(value.bytes, filename);
                status.textContent = 'Archivo exportado: ' + filename + '. Guarda también el DOCX para conservarlo en FiscalOps.';
                return;
            }
            lastBytes = value.bytes;
            recover.hidden = false;
            pending = value.bytes;
            await flush();
        }
    }
    const beforeUnload = event => {
        if (dirty || pending || saving) { event.preventDefault(); event.returnValue = ''; }
    };
    // Returning suspends the iframe. Its document, selection, undo stack and pending
    // changes stay mounted; only an explicit browser navigation can unload it.
    dialog.oncancel = event => { event.preventDefault(); dialog.close(); };
    dialog.querySelector('[data-close]').onclick = () => dialog.close();
    window.addEventListener('message', message);
    window.addEventListener('beforeunload', beforeUnload);
    dialog.onclose = () => {
        if (disposed) return;
        updateResume(); resumeButton.hidden = false;
        placeResume();
        if (changed) onSaved?.();
        returnWaiters.splice(0).forEach(resolve=>resolve(changed));
        changed = false;
    };
    // Listeners are registered before the WASM app can announce readiness.
    frame.src = '/static/vendor/wordcraft/wordcraft-web-0.14.0/index.html?host=parent&webgl&author=FiscalOps';
    dialog.showModal();
    return closed;
}

async function previewTemplate(rfc, slot) {
    const dialog = document.createElement('dialog');
    dialog.className = 'docx-preview-dialog';
    dialog.setAttribute('aria-label', 'Vista previa de plantilla');
    dialog.innerHTML = `<header class="template-studio-head"><div class="template-title-cluster"><span data-preview-company hidden></span><div><span>VISTA PREVIA · DOCX</span><h2></h2></div></div><button type="button">Cerrar</button></header><p role="status">Preparando vista previa…</p><iframe title="Páginas de la plantilla" sandbox="allow-same-origin"></iframe>`;
    dialog.querySelector('h2').textContent = rfc + ' · ' + (slot === 'primer' ? '1er requerimiento' : '2do requerimiento');
    document.body.append(dialog);
    window.CompanyIdentity.mount(dialog.querySelector('[data-preview-company]'), rfc, {registeredOnly:true});
    dialog.querySelector('button').onclick = () => dialog.close();
    dialog.onclose = () => dialog.remove();
    dialog.showModal();
    try {
        const response = await fetch(templateUrl(rfc) + '/' + slot + '/file');
        if (!response.ok) throw new Error('No se pudo abrir la plantilla.');
        const bytes = await response.arrayBuffer();
        if (!dialog.isConnected) return;
        const doc = dialog.querySelector('iframe').contentDocument;
        // Untrusted DOCX content is rendered in a scriptless, sandboxed document.
        await docx.renderAsync(bytes, doc.body, doc.head, {renderAltChunks:false, breakPages:true, renderHeaders:true, renderFooters:true});
        dialog.querySelector('[role=status]').textContent = 'Vista orientativa del DOCX guardado. El rectángulo {{REQUERIMIENTO}} indica el destino del contenido OCR.';
    } catch (error) { dialog.querySelector('[role=status]').textContent = error.message; }
}

async function editTemplateInWordCraft(item, onSaved) {
    const url = templateUrl(item.rfc) + '/' + item.id;
    let revision = item.revision;
    return openWordCraft({title:item.rfc + ' · ' + item.name, name:'Plantilla_' + item.rfc + '.docx', companyRfc:item.rfc,
        load:async () => {
            const response = await fetch(url + '/file');
            if (!response.ok) throw new Error('No se pudo abrir la plantilla.');
            const bytes = await response.arrayBuffer();
            // Fetch a matching revision, never one from an older library card.
            const digest = await crypto.subtle.digest('SHA-256', bytes);
            revision = [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
            return bytes;
        },
        save:async bytes => {
            const form = new FormData();
            form.set('revision', revision);
            form.set('file', new Blob([bytes]), 'plantilla.docx');
            const result = await templateRequest(url + '/wordcraft', {method:'PUT', body:form});
            revision = result.revision;
        }, onSaved, downloadUrl:url + '/file'});
}

async function openProfessionalWord() {
    if (retainedWordCraft?.hasPending()) { retainedWordCraft.resume(); return; }
    if (dirty && !await save(true)) return;
    if (conflicted) return;
    const picker = document.createElement('dialog');
    picker.className = 'wordcraft-picker';
    picker.innerHTML = `<h2>Abrir en WordCraft</h2><p>El escrito profesional se guarda dentro del expediente. Puedes retomarlo y exportarlo desde WordCraft. Las correcciones OCR y la revisión de numerales se conservan en Estudio Word.</p><label>Documento<select></select></label><p role="status"></p><div><button data-cancel>Cancelar</button><button data-open class="primary">Abrir editor profesional</button></div>`;
    const select = picker.querySelector('select'), status = picker.querySelector('[role=status]');
    select.add(new Option('Nuevo desde Estudio Word · formato estándar', 'standard'));
    document.body.append(picker); picker.showModal();
    picker.onclose = () => picker.remove();
    picker.querySelector('[data-cancel]').onclick = () => picker.close();
    const button = picker.querySelector('[data-open]');
    button.disabled = true;
    let hasSaved = false;
    try {
        const state = await templateRequest('/api/wordcraft/' + job + '/state');
        hasSaved = state.saved;
        if (hasSaved) { select.add(new Option('Continuar escrito profesional guardado', 'saved'), 0); select.value = 'saved'; }
        const rfc = expedientRfc();
        if (validTemplateRfc(rfc)) {
            const {templates} = await templateRequest(templateUrl(rfc));
            for (const item of templates.filter(item=>item.configured)) select.add(new Option('Nuevo con plantilla · ' + item.name, item.id));
        }
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
    button.onclick = () => {
        const choice = select.value;
        if (hasSaved && choice !== 'saved' && !confirm('Al guardar este nuevo documento se sustituirá el escrito profesional anterior. ¿Continuar?')) return;
        picker.close();
        let revision = '';
        openWordCraft({title:'Escrito profesional del expediente', name:'Escrito_FiscalOps.docx', downloadUrl:'/api/wordcraft/' + job + '/document', needsSave:choice !== 'saved', forceNew:choice !== 'saved', companyRfc:expedientRfc(),
            load:async () => {
                const params = new URLSearchParams();
                if (choice !== 'saved') params.set('fresh','true');
                if (['primer','segundo'].includes(choice)) params.set('template_id',choice);
                const response = await fetch('/api/wordcraft/' + job + '/document?' + params);
                if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'No se pudo generar el documento.'); }
                revision = response.headers.get('X-Document-Revision') || '';
                return response.arrayBuffer();
            },
            save:async bytes => {
                const form = new FormData();
                form.set('revision', revision); form.set('file', new Blob([bytes]), 'escrito.docx');
                const result = await templateRequest('/api/wordcraft/' + job + '/document', {method:'PUT', body:form});
                revision = result.revision;
            }});
    };
}
