/**
 * Start switcher widget script
 */

(function ($, elementor) {

	'use strict';

	var sectionSwitcher = function ($scope, $) {
		var $switcher = $scope.find('.bdt-switchers'),
			$settings = $switcher.data('settings'),
			$activatorSettings = $switcher.data('activator'),
			$settingsLinkWidget = $switcher.data('bdt-link-widget'),
			editMode = Boolean(elementorFrontend.isEditMode());


			if ($activatorSettings) {
				const switcherActivator = `#bdt-switcher-activator-${$activatorSettings.id}`;
				const switcherMain = `#bdt-switcher-${$activatorSettings.id}`;
			
				function toggleSwitcher(index) {
					bdtUIkit.switcher(switcherActivator).show(index);
					bdtUIkit.switcher(switcherMain).show(index);
			
					if ($settingsLinkWidget) {
						const showA = index === 0;
						$($settingsLinkWidget.linkWidgetTargetA).css({ 'opacity': showA ? 1 : 0, 'display': showA ? 'block' : 'none' });
						$($settingsLinkWidget.linkWidgetTargetB).css({ 'opacity': showA ? 0 : 1, 'display': showA ? 'none' : 'block' });
					}
				}
			
				bdtUIkit.util.on($activatorSettings.switchA, "click", () => toggleSwitcher(0));
				bdtUIkit.util.on($activatorSettings.switchB, "click", () => toggleSwitcher(1));
			}			

		if ($settings !== undefined && editMode === false) {
			var $switchAContainer = $switcher.find('.bdt-switcher > div > div > .bdt-switcher-item-a'),
				$switchBContainer = $switcher.find('.bdt-switcher > div > div > .bdt-switcher-item-b'),
				$switcherContentA = $('.elementor').find('.elementor-element' + '#' + $settings['switch-a-content']),
				$switcherContentB = $('.elementor').find('.elementor-element' + '#' + $settings['switch-b-content']);

			if ($settings.positionUnchanged !== true) {
				if ($switchAContainer.length && $switcherContentA.length) {
					$($switcherContentA).appendTo($switchAContainer);
				}

				if ($switchBContainer.length && $switcherContentB.length) {
					$($switcherContentB).appendTo($switchBContainer);
				}
			}

			if ($settings.positionUnchanged == true) {
				$('#bdt-tabs-' + $settings.id).find('.bdt-switcher').remove();

				var $switcherContentAAA = $('#' + $settings['switch-a-content']);
				var $switcherContentBBB = $('#' + $settings['switch-b-content']);

				$('#' + $settings['switch-a-content']).parent().append(`<div id="bdt-switcher-${$settings.id}" class="bdt-switcher bdt-switcher-item-content" style="width:100%;"></div>`);

				$($switcherContentAAA).appendTo($('#bdt-switcher-' + $settings.id));
				$($switcherContentBBB).appendTo($('#bdt-switcher-' + $settings.id));

				var $activeA, $activeB = '';
				if ($settings.defaultActive == 'a') {
					$activeA, $activeA = 'bdt-active';
				} else {
					$activeB = 'bdt-active';
				}

				$('#' + $settings['switch-a-content']).wrapAll('<div class="bdt-switcher-item-content-inner ' + $activeA + '"></div>');
				$('#' + $settings['switch-b-content']).wrapAll('<div class="bdt-switcher-item-content-inner ' + $activeB + '"></div>');
			}
		}


		if ($settingsLinkWidget !== undefined && editMode === false) {
			var $targetA = $($settingsLinkWidget.linkWidgetTargetA),
				$targetB = $($settingsLinkWidget.linkWidgetTargetB),
				$switcher = '#bdt-switcher-' + $settingsLinkWidget.id;

			if ($settingsLinkWidget.defaultActive == 'a') {
				$targetA.css({
					'opacity': 1,
					'display': 'block'
				});
				$targetB.css({
					'opacity': 0,
					'display': 'none'
				});
			} else {
				$targetA.css({
					'opacity': 0,
					'display': 'none'
				});
				$targetB.css({
					'opacity': 1,
					'display': 'block'
				});
			}

			$targetA.css({
				'grid-row-start': 1,
				'grid-column-start': 1
			});
			$targetB.css({
				'grid-row-start': 1,
				'grid-column-start': 1
			});

			$targetA.parent().css({
				'display': 'grid'
			});

			bdtUIkit.util.on($switcher, 'shown', function (e) {
				var index = bdtUIkit.util.index(e.target)
				if (index == 0) {
					$targetA.css({
						'opacity': 1,
						'display': 'block',
					});
					$targetB.css({
						'opacity': 0,
						'display': 'none',
					});
				} else {
					$targetB.css({
						'opacity': 1,
						'display': 'block',
					});
					$targetA.css({
						'opacity': 0,
						'display': 'none',
					});
				}

			})
		}


	};

	jQuery(window).on('elementor/frontend/init', function () {
		elementorFrontend.hooks.addAction('frontend/element_ready/bdt-switcher.default', sectionSwitcher);
	});

}(jQuery, window.elementorFrontend));

/**
 * End switcher widget script
 */