/**
 * Start advanced counter widget script
 */

;(function($, elementor) {
    'use strict';
    var widgetAdvancedCounter = function($scope, $) {
        var $AdvancedCounter = $scope.find('.bdt-advanced-counter');
        if (!$AdvancedCounter.length) {
            return;
        }

        epObserveTarget($scope[0], function () {

            var $settings = $($AdvancedCounter).data('settings');

            var options = {
                startVal: $settings.countStart ?? 0,
                numerals: $settings.language,
                decimalPlaces: $settings.decimalPlaces ?? 0,
                duration: $settings.duration ?? 0,
                useEasing: $settings.useEasing !== null,
                useGrouping: $settings.useGrouping !== null,
                separator: $settings.counterSeparator ?? '',
                decimal: $settings.decimalSymbol ?? '',
                prefix: $settings.counterPrefix ?? '',
                suffix: $settings.counterSuffix ?? '',
            };

            var demo = new CountUp($settings.id, $settings.countNumber ?? 0, options);
            if (!demo.error) {
                demo.start();
            } else {
                console.error(demo.error);
            }

        }, {
            root: null, // Use the viewport as the root
            rootMargin: '0px', // No margin around the root
            threshold: 0.8 // 80% visibility (1 - 0.8)
        });

    };
    jQuery(window).on('elementor/frontend/init', function() {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-total-count.default', widgetAdvancedCounter);
    });
}(jQuery, window.elementorFrontend));

/**
 * End advanced counter widget script
 */

