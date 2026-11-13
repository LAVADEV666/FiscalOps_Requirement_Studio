'use strict';

const validTemplateRfc = value => /^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$/.test(value);
const templateUrl = rfc => '/api/templates/' + encodeURIComponent(rfc);
const templateIdentityIcons = {building:'🏢', briefcase:'💼', factory:'🏭', shop:'🏪', bank:'🏦', leaf:'🌿', star:'⭐', document:'📄'};

async function templateRequest(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'No se pudo completar la operación.');
    return result;
}

function setupTemplateLibrary(container, initialRfc = '') {
    if (container.loadTemplateRfc) {
        container.loadTemplateRfc(initialRfc);
        return;
    }
    container.innerHTML = `
        <div class="template-library-heading"><span class="card-icon icon-action">${desktopIcon('template')}</span><div><span class="eyebrow">BIBLIOTECA DOCUMENTAL</span><h2>Plantillas Word por RFC</h2></div></div>
        <p>Crea una plantilla desde cero o importa un DOCX para el 1er y 2do requerimiento. Diseña en WordCraft y coloca el rectángulo <code>{{REQUERIMIENTO}}</code> donde irá el contenido OCR de Estudio Word.</p>
        <p><a class="template-example-link icon-action" href="/api/template-example" download>${desktopIcon('download')} Descargar Word de ejemplo</a></p>
        <div class="template-rfc-gallery" data-template-gallery aria-label="Biblioteca por RFC"></div>
        <form class="template-form" data-template-search>
            <label>RFC <input name="rfc" maxlength="13" required></label><button class="soft-button icon-action">${desktopIcon('folder')} Buscar plantillas</button>
        </form>
        <p role="status" data-template-status></p>
        <div data-template-customer hidden>
            <div class="template-company-context" data-template-company hidden></div>
            <form class="template-identity" data-template-identity>
                <span data-rfc-badge aria-hidden="true"></span><strong data-rfc-label></strong>
                <label>Icono del RFC <select name="icon">${Object.entries(templateIdentityIcons).map(([key,value])=>`<option value="${key}">${value} ${({building:'Empresa',briefcase:'Servicios',factory:'Industria',shop:'Comercio',bank:'Finanzas',leaf:'Campo',star:'Destacado',document:'Documento'})[key]}</option>`).join('')}</select></label>
                <label>Color <input type="color" name="color" value="#6b4389"></label><button type="submit">Guardar identidad</button>
            </form>
            <label>Tipo de requerimiento <select data-template-select></select></label>
            <div class="template-create-actions" data-template-create hidden><span>Crear plantilla:</span><button type="button" data-create="blank">En blanco</button><button type="button" data-create="letter">Carta base</button><span>o importa tu Word:</span></div>
            <form class="template-form" data-template-import hidden>
                <label>Documento base <input type="file" name="file" accept=".docx" required></label>
                <button class="primary icon-action">${desktopIcon('upload')} Importar y guardar</button>
            </form>
            <section data-template-editor></section>
            <details data-template-legacy hidden>
                <summary>Plantillas de la versión anterior</summary>
                <p>Descarga el DOCX que quieras conservar y cárgalo en el tipo de requerimiento que le corresponda.</p>
                <ul></ul>
            </details>
        </div>`;
    const find = selector => container.querySelector(selector);
    const search = find('[data-template-search]'), customer = find('[data-template-customer]');
    const status = find('[data-template-status]'), select = find('[data-template-select]');
    const editor = find('[data-template-editor]'), rfcField = search.elements.rfc;
    const importForm = find('[data-template-import]'), legacyList = find('[data-template-legacy]');
    const creation = find('[data-template-create]'), identityForm = find('[data-template-identity]');
    let slots = [];
    let rfc = '', busy = false;

    async function refreshGallery() {
        try {
            const {customers} = await templateRequest('/api/template-profiles');
            find('[data-template-gallery]').replaceChildren(...customers.map(profile => {
                const button = document.createElement('button');
                button.type = 'button';
                const badge = document.createElement('span');
                badge.className = 'template-rfc-icon';
                badge.textContent = templateIdentityIcons[profile.icon] || '🏢';
                if (/^#[0-9a-f]{6}$/i.test(profile.color)) badge.style.backgroundColor = profile.color;
                const label = document.createElement('span');
                label.textContent = profile.rfc;
                const count = document.createElement('small');
                count.textContent = profile.templates.filter(item=>item.configured).length + ' / 2 plantillas';
                label.append(count);
                button.append(badge, label);
                window.CompanyIdentity.mount(badge, profile.rfc, {icon:templateIdentityIcons[profile.icon], color:profile.color});
                button.onclick = () => { rfcField.value = profile.rfc; search.requestSubmit(); };
                return button;
            }));
        } catch { /* The RFC search remains available if the gallery cannot load. */ }
    }

    async function perform(action) {
        if (busy) return;
        busy = true;
        status.dataset.busy = 'true';
        status.textContent = 'Procesando…';
        const inputs = [...container.querySelectorAll('button, input, select')];
        inputs.forEach(input => input.disabled = true);
        try { await action(); }
        catch (error) { status.textContent = error.message; }
        finally {
            busy = false;
            delete status.dataset.busy;
            inputs.forEach(input => input.disabled = false);
        }
    }

    async function refresh(id = '') {
        const [{templates, legacy}, profile] = await Promise.all([
            templateRequest(templateUrl(rfc) + '?include_legacy=true'),
            templateRequest('/api/template-profiles/' + encodeURIComponent(rfc))
        ]);
        identityForm.elements.icon.value = profile.icon;
        identityForm.elements.color.value = profile.color;
        find('[data-rfc-label]').textContent = rfc;
        window.CompanyIdentity.mount(find('[data-template-company]'), rfc, {registeredOnly:true, showName:true});
        paintIdentity();
        slots = templates;
        select.replaceChildren(new Option('Selecciona el tipo de requerimiento', ''));
        for (const item of slots) {
            select.add(new Option(item.name + (item.configured ? ' · Guardada' : ' · Sin plantilla'), item.id));
        }
        legacyList.hidden = !legacy.length;
        legacyList.querySelector('ul').replaceChildren(...legacy.map(item => {
            const row = document.createElement('li');
            const link = document.createElement('a');
            link.href = templateUrl(rfc) + '/legacy/' + item.id;
            link.download = '';
            link.textContent = item.name;
            row.append(link);
            return row;
        }));
        customer.hidden = false;
        select.value = id;
        await refreshGallery();
    }

    function showEditorLink(item, open = false) {
        importForm.hidden = true;
        creation.hidden = true;
        editor.innerHTML = `
            <div class="template-saved-card">
                <div><span class="eyebrow">DOCX GUARDADO</span><h3></h3><p>Edita el diseño completo en WordCraft o coloca el rectángulo OCR en el editor de bloques.</p></div>
                <div class="template-card-actions"><button type="button" data-preview>Vista previa</button><button type="button" data-quick>Editar bloques y OCR</button><button type="button" class="primary" data-professional>Abrir WordCraft</button></div>
            </div>`;
        editor.querySelector('h3').textContent = item.name;
        const button = editor.querySelector('[data-quick]');
        button.onclick = () => perform(async () => {
            const current = await templateRequest(templateUrl(rfc) + '/' + item.id);
            status.textContent = '';
            openTemplateEditor(current);
        });
        editor.querySelector('[data-preview]').onclick = () => previewTemplate(rfc, item.id);
        editor.querySelector('[data-professional]').onclick = async () => {
            let current;
            await perform(async () => { current = await templateRequest(templateUrl(rfc) + '/' + item.id); status.textContent = ''; });
            if (current) editTemplateInWordCraft(current);
        };
        if (open) openTemplateEditor(item);
    }

    function paintIdentity() {
        const badge = find('[data-rfc-badge]');
        badge.textContent = templateIdentityIcons[identityForm.elements.icon.value] || '🏢';
        badge.style.backgroundColor = identityForm.elements.color.value;
        window.CompanyIdentity.mount(badge, rfc, {icon:templateIdentityIcons[identityForm.elements.icon.value], color:identityForm.elements.color.value});
    }
    identityForm.oninput = paintIdentity;
    identityForm.onsubmit = event => {
        event.preventDefault();
        perform(async () => {
            await templateRequest('/api/template-profiles/' + encodeURIComponent(rfc), {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({icon:identityForm.elements.icon.value, color:identityForm.elements.color.value})});
            status.textContent = 'Identidad del RFC guardada.';
            await refreshGallery();
        });
    };
    creation.querySelectorAll('[data-create]').forEach(button => button.onclick = () => perform(async () => {
        const item = await templateRequest(templateUrl(rfc) + '/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({slot:select.value, style:button.dataset.create})});
        await refresh(item.id);
        showEditorLink(item, true);
        status.textContent = 'Plantilla creada. Agrega tu diseño en WordCraft o coloca el rectángulo OCR.';
    }));

    search.onsubmit = event => {
        event.preventDefault();
        const value = rfcField.value.trim().toUpperCase();
        if (!validTemplateRfc(value)) {
            status.textContent = 'Escribe un RFC de 12 o 13 caracteres.';
            return;
        }
        perform(async () => {
            customer.hidden = true;
            editor.replaceChildren();
            importForm.reset();
            importForm.hidden = true;
            creation.hidden = true;
            rfc = value;
            await refresh();
            status.textContent = 'Mostrando plantillas para ' + rfc + '.';
        });
    };
    rfcField.oninput = () => {
        customer.hidden = rfcField.value.trim().toUpperCase() !== rfc;
    };
    select.onchange = () => {
        editor.replaceChildren();
        importForm.reset();
        const slot = slots.find(item => item.id === select.value);
        importForm.hidden = !slot || slot.configured;
        creation.hidden = !slot || slot.configured;
        status.textContent = '';
        if (slot?.configured) showEditorLink(slot);
    };
    importForm.onsubmit = event => {
        event.preventDefault();
        const form = event.currentTarget, payload = new FormData(form);
        payload.set('slot', select.value);
        perform(async () => {
            const item = await templateRequest(templateUrl(rfc), {method:'POST', body:payload});
            form.reset();
            await refresh(item.id);
            showEditorLink(item, true);
            status.textContent = 'Plantilla importada.';
        });
    };
    let lastContext;
    container.loadTemplateRfc = value => {
        if (value === lastContext) return;
        lastContext = value;
        rfcField.value = value;
        rfcField.oninput();
        if (validTemplateRfc(value)) search.requestSubmit();
    };
    container.loadTemplateRfc(initialRfc);
    refreshGallery();
}

document.querySelectorAll('[data-template-library]').forEach(container => setupTemplateLibrary(container));
