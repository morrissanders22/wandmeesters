/**
 * Start advanced icon box widget script
 */

(function ($, elementor) {

    'use strict';
    var widgetAdvancedIconBox = function ($scope, $) {

        var $avdDivider = $scope.find('.bdt-ep-advanced-icon-box'),
            divider = $($avdDivider).find('.bdt-ep-advanced-icon-box-separator-wrap > img');

        if (!$avdDivider.length && !divider.length) {
            return;
        }

        epObserveTarget($scope[0], function () {
            bdtUIkit.svg(divider, {
                strokeAnimation: true
            });
        });

    };


    jQuery(window).on('elementor/frontend/init', function () {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-advanced-icon-box.default', widgetAdvancedIconBox);
    });

}(jQuery, window.elementorFrontend));

/**
 * End advanced icon box widget script
 */

