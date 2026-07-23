(function ($, elementor) {
  $(window).on("elementor/frontend/init", function () {
    var ModuleHandler = elementorModules.frontend.handlers.Base,
      AnimatedGradientBackground;

    AnimatedGradientBackground = ModuleHandler.extend({
      bindEvents: function () {
        this.run();
      },

      getDefaultSettings: function () {
        return {
          allowHTML: true,
        };
      },

      onElementChange: debounce(function (prop) {
        if (prop.indexOf('element_pack_agbg_') !== -1) {
          this.run();
        }
      }, 400),

      settings: function (key) {
        return this.getElementSettings("element_pack_agbg_" + key);
      },

      // Helper function to parse and standardize colors to desired formats
      parseColor: function (color) {
        // Convert RGBA to 6-digit HEX if alpha is 1
        if (/^rgba?\((\d+),\s*(\d+),\s*(\d+),?\s*([\d.]*)\)$/.test(color)) {
          const [_, r, g, b, a = 1] = color.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+),?\s*([\d.]*)\)$/);
          const alpha = parseFloat(a);
          if (alpha === 1) {
            // If alpha is 1, convert to 6-digit HEX format
            return `#${((1 << 24) + (parseInt(r) << 16) + (parseInt(g) << 8) + parseInt(b)).toString(16).slice(1)}`;
          }
          return `rgba(${r}, ${g}, ${b}, .${a.toString().split('.')[1] || 0})`; // Format as .decimal if alpha < 1
        }

        // Convert 8-digit HEXA (#RRGGBBAA) to 6-digit HEX if alpha is 1
        if (/^#([A-Fa-f0-9]{8})$/.test(color)) {
          const rgba = color.match(/[A-Fa-f0-9]{2}/g).map((hex) => parseInt(hex, 16));
          const alpha = parseFloat((rgba[3] / 255).toFixed(2));
          if (alpha === 1) {
            return `#${color.slice(1, 7)}`; // Remove alpha part if 100% opaque
          }
          return `rgba(${rgba[0]}, ${rgba[1]}, ${rgba[2]}, .${alpha.toString().split('.')[1] || 0})`;
        }

        // Convert 6-digit HEX to standard 6-digit HEX (no changes needed)
        if (/^#([A-Fa-f0-9]{6})$/.test(color)) {
          return color.toLowerCase();
        }

        // Handle HSLA, standardizing alpha to .decimal format
        if (/^hsla?\((\d+),\s*([\d.]+)%,\s*([\d.]+)%,?\s*([\d.]*)\)$/.test(color)) {
          const [_, h, s, l, a = 1] = color.match(/^hsla?\((\d+),\s*([\d.]+)%,\s*([\d.]+)%,?\s*([\d.]*)\)$/);
          const alpha = parseFloat(a);
          if (alpha === 1) {
            return `hsl(${h}, ${s}%, ${l}%)`; // No alpha if fully opaque
          }
          return `hsla(${h}, ${s}%, ${l}%, .${a.toString().split('.')[1] || 0})`; // .decimal format for alpha < 1
        }

        return color; // Return color as-is for named colors or other formats
      },

      run: function () {
        if (this.settings('show') !== 'yes') {
          return;
        }
        const sectionID = this.$element.data("id");
        const widgetContainer = document.querySelector(".elementor-element-" + sectionID);
        const checkClass = $(widgetContainer).find(".bdt-animated-gradient-background");

        if ($(checkClass).length < 1) {
          $(widgetContainer).prepend('<canvas id="canvas-basic-' + sectionID + '" class="bdt-animated-gradient-background"></canvas>');
        }

        const gradientID = $(widgetContainer).find(".bdt-animated-gradient-background").attr("id");

        let color_list = this.settings("color_list");
        let colors = color_list.map((color) => [
          this.parseColor(color.start_color),
          this.parseColor(color.end_color)
        ]);

        var direction = (this.settings("direction") !== undefined) ? this.settings('direction') : 'diagonal';
        var transitionSpeed = (this.settings("transitionSpeed") !== undefined) ? this.settings('transitionSpeed.size') : '5500';
        
        var granimInstance = new Granim({
          element: "#" + gradientID,
          direction: direction,
          isPausedWhenNotInView: true,
          states: {
            "default-state": {
              gradients: colors,
              transitionSpeed: transitionSpeed,
            },
          },
        });
      },
    });

    elementorFrontend.hooks.addAction(
      "frontend/element_ready/section",
      function ($scope) {
        elementorFrontend.elementsHandler.addHandler(AnimatedGradientBackground, {
          $element: $scope,
        });
      }
    );

    elementorFrontend.hooks.addAction(
      "frontend/element_ready/container",
      function ($scope) {
        elementorFrontend.elementsHandler.addHandler(AnimatedGradientBackground, {
          $element: $scope,
        });
      }
    );

  });
})(jQuery, window.elementorFrontend);
