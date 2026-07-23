/**
 * Start dual button widget script
 */

(function ($, elementor) {
  "use strict";

  var widgetDualButton = function ($scope, $) {
    var $buttons = $scope.find(".bdt-dual-button .bdt-ep-button[data-onclick]");
  
    if (!$buttons.length) return;

    $buttons.on("click", function (event) {
        event.preventDefault();

        var functionName = $(this).data("onclick")?.trim();
        
        if (functionName) {
            functionName = functionName.replace(/[\(\);\s]/g, '');
            
            if (typeof window[functionName] === "function") {
                window[functionName]();
            } else {
                console.warn(`Function "${functionName}" is not defined.`);
            }
        }
    });
};


  jQuery(window).on("elementor/frontend/init", function () {
    elementorFrontend.hooks.addAction(
      "frontend/element_ready/bdt-dual-button.default",
      widgetDualButton
    );
  });
})(jQuery, window.elementorFrontend);

/**
 * End dual button widget script
 */
