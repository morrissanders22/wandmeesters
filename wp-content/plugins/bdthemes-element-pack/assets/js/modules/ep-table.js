/**
 * Start table widget script
 */

(function ($, elementor) {

    'use strict';

    var widgetTable = function ($scope, $) {

        var $tableContainer = $scope.find('.bdt-data-table'),
            $settings = $tableContainer.data('settings'),
            $table = $tableContainer.find('> table'),
            editMode = Boolean(elementorFrontend.isEditMode());

        if (!$tableContainer.length) {
            return;
        }

        $settings.language = window.ElementPackConfig.data_table.language;

        if (editMode) {
            DataTable.ext.errMode = function (s, tn, msg) {
                console.log(msg, tn);
            };
        }

        $($table).DataTable($settings);

    };


    jQuery(window).on('elementor/frontend/init', function () {
        elementorFrontend.hooks.addAction('frontend/element_ready/bdt-table.default', widgetTable);
    });

}(jQuery, window.elementorFrontend));

/**
 * End table widget script
 */