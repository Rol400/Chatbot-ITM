/* Recorrido de la portada: controles nativos accesibles con teclado. */
(function () {
  'use strict';
  var buttons = document.querySelectorAll('.s3-step[data-step]');
  var previews = document.querySelectorAll('.kb-preview');
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      buttons.forEach(function (item) { item.setAttribute('aria-pressed', String(item === button)); });
      previews.forEach(function (preview) {
        var selected = preview.id === button.getAttribute('aria-controls');
        preview.hidden = !selected;
        preview.classList.toggle('s3-view', selected);
      });
    });
  });
})();
