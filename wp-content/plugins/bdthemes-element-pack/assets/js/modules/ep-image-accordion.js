(function ($, elementor) {
  "use strict";

  var widgetImageAccordion = function ($scope, $) {
    var $imageAccordion = $scope.find(".bdt-ep-image-accordion"),
      $settings = $imageAccordion.data("settings");

    var accordionItem = $imageAccordion.find(".bdt-ep-image-accordion-item");
    var totalItems = $imageAccordion.children().length;

    // Make each accordion item focusable
    accordionItem.attr('tabindex', '0');

    if (
      $settings.activeItem == true &&
      $settings.activeItemNumber <= totalItems
    ) {
      $imageAccordion.find(".bdt-ep-image-accordion-item").removeClass("active");
      $imageAccordion.children().eq($settings.activeItemNumber - 1).addClass("active");
    }

    // Mouse event
    $(accordionItem).on($settings.mouse_event, function () {
      $(this).siblings().removeClass("active");
      $(this).addClass("active");
    });

    // Keyboard focus event
    $(accordionItem).on('focus', function () {
      $(this).siblings().removeClass("active");
      $(this).addClass("active");
    });

    // Keydown event for Enter or Space key
    $(accordionItem).on('keydown', function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        $(this).siblings().removeClass("active");
        $(this).addClass("active");
      }
    });

    if ($settings.activeItem != true) {
      $("body").on($settings.mouse_event, function (e) {
        if (
          e.target.$imageAccordion == "bdt-ep-image-accordion" ||
          $(e.target).closest(".bdt-ep-image-accordion").length
        ) {
          // inside accordion, do nothing
        } else {
          $imageAccordion.find(".bdt-ep-image-accordion-item").removeClass("active");
        }
      });
    }

    // Swiping (unchanged)
    function handleSwipe(event) {
      var deltaX = touchendX - touchstartX;
      var hasPrev = $(event.currentTarget).prev();
      var hasNext = $(event.currentTarget).next();

      if (deltaX > 50) {
        if (hasPrev.length) {
          $(accordionItem).removeClass("active");
          hasPrev.addClass("active");
        }
      } else if (deltaX < -50) {
        if (hasNext.length) {
          $(accordionItem).removeClass("active");
          hasNext.addClass("active");
        }
      }
    }

    if ($settings.swiping) {
      var touchstartX = 0;
      var touchendX = 0;

      $(accordionItem).on("touchstart", function (event) {
        touchstartX = event.changedTouches[0].screenX;
      });

      $(accordionItem).on("touchend", function (event) {
        touchendX = event.changedTouches[0].screenX;
        handleSwipe(event);
      });
    }

    // Inactive Item
    if ($settings.inactiveItemOverlay) {
      $(accordionItem).on($settings.mouse_event, function (event) {
        event.stopPropagation();
        if ($(this).hasClass("active")) {
          $(this).removeClass("bdt-inactive").siblings().addClass("bdt-inactive");
        } else {
          $(this).siblings().removeClass("bdt-inactive");
        }
      });
      $(document).on($settings.mouse_event, function () {
        $(accordionItem).removeClass("bdt-inactive");
      });
    }
  };

  jQuery(window).on("elementor/frontend/init", function () {
    elementorFrontend.hooks.addAction(
      "frontend/element_ready/bdt-image-accordion.default",
      widgetImageAccordion
    );
  });
})(jQuery, window.elementorFrontend);
