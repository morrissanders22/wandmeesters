/**
 * Start advanced counter widget script
 */
; (function ($, elementor) {
    'use strict';
    var widgetAdvancedCounter = function ($scope, $) {
        var $AdvancedCounter = $scope.find('.bdt-ep-advanced-counter');
        if (!$AdvancedCounter.length) {
            return;
        }

        let $this = $($scope[0]).find('.bdt-ep-advanced-counter'),
            $settings = $this.data('settings');

        let countNumber = $settings.countNumber ?? 0;

        let options = {
            startVal: $settings.countStart ?? 0,
            numerals: $settings.language,
            decimalPlaces: $settings.decimalPlaces ?? 0,
            duration: $settings.duration ?? 0,
            useEasing: !($settings.useEasing == null),
            useGrouping: !($settings.useGrouping == null),
            separator: $settings.counterSeparator ?? '',
            decimal: $settings.decimalSymbol ?? '',
            prefix: $settings.counterPrefix ?? '',
            suffix: $settings.counterSuffix ?? '',
        };

        epObserveTarget($scope[0], function () {

            var demo = new CountUp($settings.id, countNumber, options);

            if (!demo.error) {
                demo.start();
            } else {
                console.error(demo.error);
            }

        });

    };
    jQuery(window).on('elementor/frontend/init', function () {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-advanced-counter.default', widgetAdvancedCounter);
    });
}(jQuery, window.elementorFrontend));

/**
 * End advanced counter widget script
 */

