'use strict';

function desktopIcon(name) {
    return `<svg class="ui-icon" aria-hidden="true" focusable="false"><use href="/static/icons.svg?v=1#${name}"></use></svg>`;
}

document.querySelectorAll('[data-icon]').forEach(node => {
    node.insertAdjacentHTML('afterbegin', desktopIcon(node.dataset.icon));
});

function ssgtSymbolHTML() {
    return '<span class="ssgt-symbol ssgt-rotor" aria-hidden="true"><img src="/static/ssgt-symbol.png" alt="" draggable="false"></span>';
}
