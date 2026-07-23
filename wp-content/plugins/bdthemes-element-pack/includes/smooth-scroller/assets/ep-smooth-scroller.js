(function ($) {
  "use strict";

  $(document).ready(function () {

    if ($('.elementor-editor-active').length > 0) {
      console.log('Element Pack Smooth Scroller is disabled in Elementor Editor');
      return;
    }

    const lenis = new Lenis();
    function raf(time) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);
  });
  
})(jQuery);
