jQuery(document).ready(function () {
    jQuery('body').on('click', '.bdt-element-link', function () {
        var $el = jQuery(this),
            settings = $el.data('ep-wrapper-link');

        if (!settings || !settings.url || !/^https?:\/\//.test(settings.url)) {
            return; // invalid or unsafe URL
        }

        var id = 'bdt-element-link-' + $el.data('id');

        if (jQuery('#' + id).length === 0) {
            jQuery('body').append(
                jQuery('<a/>').prop({
                    target: settings.is_external ? '_blank' : '_self',
                    href: settings.url,
                    class: 'bdt-hidden',
                    id: id,
                    rel: settings.is_external ? 'noopener noreferrer' : ''
                })
            );
        }

        jQuery('#' + id)[0].click();
    });
});
