// Upload form: drag & drop, client-side type/size check (server re-checks file contents).
import { $ } from "../core/util.js";

const OK = /\.(pdf|png|jpe?g|webp)$/i;

export default function init() {
  const zone = $("[data-dropzone]");
  if (!zone) return;
  const input = $('input[type="file"]', zone);
  const label = $("[data-dz-file]", zone);
  const err = document.querySelector('[data-error-for="file"]');
  const maxMb = Number(input.dataset.maxMb || 10);
  const title = document.getElementById("title");

  function show() {
    const f = input.files?.[0];
    err.textContent = "";
    input.removeAttribute("aria-invalid");
    if (!f) {
      label.hidden = true;
      return;
    }
    if (!OK.test(f.name)) err.textContent = "Choose a PDF, PNG, JPG or WebP file.";
    else if (f.size > maxMb * 1024 * 1024) err.textContent = `This file is ${(f.size / 1048576).toFixed(1)} MB; the limit is ${maxMb} MB.`;
    if (err.textContent) {
      input.setAttribute("aria-invalid", "true");
      input.value = "";
      label.hidden = true;
      return;
    }
    label.textContent = `${f.name} · ${(f.size / 1024).toFixed(0)} KB`;
    label.hidden = false;
    if (title && !title.value) title.value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").slice(0, 200);
  }

  input.addEventListener("change", show);
  ["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => { e.preventDefault(); zone.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((t) => zone.addEventListener(t, () => zone.classList.remove("is-over")));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer?.files?.length) {
      input.files = e.dataTransfer.files;
      show();
    }
  });
}
