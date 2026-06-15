/**
 * Start image accordion widget script
 */

; (function ($, elementor) {

    'use strict';
    $(window).on('elementor/frontend/init', function () {
        var ModuleHandler = elementorModules.frontend.handlers.Base,
            ImagePrallaxEffects;

        ImagePrallaxEffects = ModuleHandler.extend({
            bindEvents: function () {
                this.run();
            },
            onElementChange: debounce(function (prop) {
                if (prop.indexOf('element_pack_image_parallax_effects_') !== -1) {
                    this.run();
                }
            }, 400),

            settings: function (key) {
                return this.getElementSettings('element_pack_image_parallax_effects_' + key);
            },
            run: function () {
                var options = this.getDefaultSettings(),
                    element = this.$element[0],
                    widgetContainer = $(element).find('.elementor-image');
                let image = widgetContainer.find('img').attr('src');

                if ('yes' === this.settings('enable')) {
                    let $content = `<div class="bdt-image-parallax-wrapper" bdt-parallax="bgy: -200" style="background-image: url(${image});"></div>`;
                    $(widgetContainer).append($content);
                }
            }
        });

        elementorFrontend.hooks.addAction('frontend/element_ready/widget', function ($scope) {
            elementorFrontend.elementsHandler.addHandler(ImagePrallaxEffects, {
                $element: $scope
            });
        });
    });

}(jQuery, window.elementorFrontend));

/**
 * End image expand widget script
 */
