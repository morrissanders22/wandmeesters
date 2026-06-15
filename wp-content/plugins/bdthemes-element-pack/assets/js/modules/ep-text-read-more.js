; (function ($, elementor) {
$(window).on('elementor/frontend/init', function () {
    let ModuleHandler = elementorModules.frontend.handlers.Base,
        textReadMore;

    textReadMore = ModuleHandler.extend({
        bindEvents: function () {
            this.run();
        },
        getDefaultSettings: function () {
            return {
                allowHTML: true,
            };
        },

        onElementChange: debounce(function (prop) {
            if (prop.indexOf('ep_text_read_more_') !== -1) {
                this.run();
            }
        }, 400),

        settings: function (key) {
            return this.getElementSettings('ep_text_read_more_' + key);
        },

        run: function () {
            var tileScroll_ID = 'bdt-tile-scroll-container-' + this.$element.data('id'),
                widgetID = this.$element.data('id'),
                widgetContainer = $('.elementor-element-' + widgetID);
            var button_style = this.settings('button_style');
            if (this.settings('enable') === 'yes') {
                const dReadMore = new DReadMore();

                window.addEventListener('resize', function () {
                    dReadMore.forEach(function (item) {
                        item.update();
                    });
                });
            } else {
                return;
            }

        }
    });

    elementorFrontend.hooks.addAction('frontend/element_ready/widget', function ($scope) {
        elementorFrontend.elementsHandler.addHandler(textReadMore, {
            $element: $scope
        });
    });
});
})(jQuery, window.elementorFrontend);
