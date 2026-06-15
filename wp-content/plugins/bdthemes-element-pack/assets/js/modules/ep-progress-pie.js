/**
 * Start progress pie widget script
 */

(function ($, elementor) {

    'use strict';

    var widgetProgressPie = function ($scope, $) {

        var $progressPie = $scope.find('.bdt-progress-pie');

        if (!$progressPie.length) {
            return;
        }

        epObserveTarget($scope[0], function () {
            var $this = $($progressPie);

            $this.asPieProgress({
                namespace: 'pieProgress',
                classes: {
                    svg: 'bdt-progress-pie-svg',
                    number: 'bdt-progress-pie-number',
                    content: 'bdt-progress-pie-content'
                }
            });

            $this.asPieProgress('start');

        }, {
            root: null, // Use the viewport as the root
            rootMargin: '0px', // No margin around the root
            threshold: 1 // 80% visibility (1 - 0.8)
        });

    };


    jQuery(window).on('elementor/frontend/init', function () {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-progress-pie.default', widgetProgressPie);
    });

}(jQuery, window.elementorFrontend));

/**
 * End progress pie widget script
 */

