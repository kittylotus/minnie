// Selected official Lucide SVGs are bundled locally in vendor/lucide.svg.
export function icon(name){
  return `<svg class="icon" aria-hidden="true" focusable="false" viewBox="0 0 24 24"><use href="/vendor/lucide.svg#${name}"></use></svg>`;
}
