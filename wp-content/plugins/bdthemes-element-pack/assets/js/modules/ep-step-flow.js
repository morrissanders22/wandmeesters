/**
 * Start step flow widget script
 */

(function ($, elementor) {

    'use strict';

    var widgetStepFlow = function ($scope, $) {

        var $avdDivider = $scope.find('.bdt-step-flow'),
            divider = $($avdDivider).find('.bdt-title-separator-wrapper > img');

        if (!$avdDivider.length) {
            return;
        }

        epObserveTarget($scope[0], function () {
            bdtUIkit.svg(divider, {
                strokeAnimation: true
            });
        }, {
            root: null, // Use the viewport as the root
            rootMargin: '0px', // No margin around the root
            threshold: 0.8 // 80% visibility (1 - 0.8)
        });

    };


    jQuery(window).on('elementor/frontend/init', function () {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-step-flow.default', widgetStepFlow);
    });

}(jQuery, window.elementorFrontend));

/**
 * End step flow widget script
 */

