;( function( $, document ) {
    'use strict';

    var epVariationSwatches = function( $form ) {
        var self = this;

        self.$form            = $form;
        self.$attributeFields = $form.find( '.variations select' );
        self.variationData    = $form.data( 'product_variations' );

        // Initial states.
        $form.off( '.ep-variation-swatches' );

        // Add a new CSS to the form.
        if ( $form.find( '.ep-variation-swatches__wrapper' ).length ) {
            $form.addClass( 'swatches-support' );
        }

        // Methods.
        self.getChosenAttributes = self.getChosenAttributes.bind( self );

        // Events.
        $form.on( 'click.ep-variation-swatches', '.ep-variation-swatches__item', { epVariationSwatches: self }, self.onSelect );
        $form.on( 'change.ep-variation-swatches', '.variations select', { epVariationSwatches: self }, self.onValueChange );
        $form.on( 'keydown.ep-variation-swatches', '.ep-variation-swatches__item', { epVariationSwatches: self }, self.onKeyPress );
        $form.on( 'woocommerce_update_variation_values.ep-variation-swatches', { epVariationSwatches: self }, self.onUpdateAttributes );

        if ( ep_variation_swatches_params.show_selected_label ) {
            $form.on( 'change.ep-variation-swatches', '.value select', { epVariationSwatches: self }, self.updateLabel );
            $form.on( 'wc_variation_form.ep-variation-swatches', { epVariationSwatches: self }, self.updateAllLabels );
        }

        $( document.body ).trigger( 'ep_variation_swatches', self );
    };

    /**
     * Update the selected value on selection change
     */
    epVariationSwatches.prototype.onSelect = function( event ) {
        event.preventDefault();

        var $el = $( this );

        if ( $el.hasClass( 'disabled' ) || $el.data( 'disabled' ) ) {
            return;
        }

        var $select = $el.closest( '.ep-variation-swatches' ).find( 'select' ),
            value = ! $el.hasClass( 'selected' ) ? $el.data( 'value' ) : '';


        $select.trigger( 'focusin' ); // Compatible with old version of WooCommerce.
        $select.val( value );
        $select.trigger( 'change' );
    };

    epVariationSwatches.prototype.onValueChange = function () {
        var $select = $( this ),
            $swatches = $select.closest( '.ep-variation-swatches' ),
            value = $select.val();

        if ( ! $swatches.length ) {
            return;
        }

        $swatches.find( '.ep-variation-swatches__item.selected' )
            .removeClass( 'selected' )
            .attr( 'aria-pressed', false );

        if ( value ) {
            $swatches
                .find( '.ep-variation-swatches__item' )
                .filter( function() { return this.dataset.value === value; } )
                .addClass( 'selected' )
                .attr( 'aria-pressed', true );
        }
    }

    epVariationSwatches.prototype.onKeyPress = function( event ) {
        if ( event.keyCode && 32 === event.keyCode || event.key && ' ' === event.key || event.keyCode && 13 === event.keyCode || event.key && 'enter' === event.key.toLowerCase() ) {
            event.preventDefault();

            $( this ).trigger( 'click.ep-variation-swatches' );
        }
    }

    epVariationSwatches.prototype.onUpdateAttributes = function( event ) {
        var self              = event.data.epVariationSwatches ,
            attributes        = self.getChosenAttributes() ,
            currentAttributes = attributes.data;

        // Reset if no attributes chosen.
        if ( ! attributes.chosenCount ) {
            self.$form.find( '.ep-variation-swatches__item' ).removeClass( 'selected disabled' ).data( 'disabled', false ).attr( 'tabindex', 0 );

            // return;
        }

        setTimeout( function() {
            // Disable invalid swatches.
            self.$attributeFields.each( function() {
                var $select = $( this ),
                    $items = $select.siblings( '.ep-variation-swatches__wrapper' ).find( '.ep-variation-swatches__item' );

                $items.each( function() {
                    var $item = $( this ),
                        $option = $select.find( 'option[value="' + $item.data( 'value' ) + '"]' );

                    if ( ! $option.length || $option.prop( 'disabled' ) ) {
                        $item.addClass( 'disabled' ).removeClass( 'selected' ).data( 'disabled', true ).attr( 'tabindex', -1 );
                    } else {
                        $item.removeClass( 'disabled' ).data( 'disabled', false ).attr( 'tabindex', 0 );
                    }
                } );
            } );
        }, 10 );
    };

    epVariationSwatches.prototype.updateLabel = function( event ) {
        event.data.epVariationSwatches.appendSelectedLabel( this );
    }

    epVariationSwatches.prototype.updateAllLabels = function( event ) {
        var self = event.data.epVariationSwatches;

        self.$form.find( '.value select' ).each( function() {
            self.appendSelectedLabel( this );
        } );
    }
    epVariationSwatches.prototype.appendSelectedLabel = function( select ) {
        var $label = $( select ).closest( '.value' ).siblings( '.label' ).find( 'label' ),
            $holder = $label.find( '.ep-variation-swatches__selected-label' );

        if ( ! $holder.length ) {
            $holder = $( '<span class="ep-variation-swatches__selected-label" />' );

            $label.append( $holder )
        }

        if ( select.value ) {
            $holder.text( select.options[ select.selectedIndex ].text ).show();
        } else {
            $holder.text( '' ).hide();
        }
    }

    /**
     * Get chosen attributes from form.
     * @see woocommerce/assets/js/frontend/add-to-cart-variation.js
     * @return array
     */
    epVariationSwatches.prototype.getChosenAttributes = function() {
        var data   = {};
        var count  = 0;
        var chosen = 0;

        this.$attributeFields.each( function() {
            var attribute_name = $( this ).data( 'attribute_name' ) || $( this ).attr( 'name' );
            var value          = $( this ).val() || '';

            if ( value.length > 0 ) {
                chosen ++;
            }

            count ++;
            data[ attribute_name ] = value;
        });

        return {
            'count'      : count,
            'chosenCount': chosen,
            'data'       : data
        };
    };

    /**
     * Function to call ep_variation_swatches on jquery selector.
     */
    $.fn.ep_variation_swatches = function() {
        new epVariationSwatches( this );
        return this;
    };

    /**
     * Function to init variation swatches on all variation forms
     */
    function init_variation_swatches() {
        $( '.variations_form:not(.swatches-support)' ).each( function() {
            $( this ).ep_variation_swatches();
        } );
    }

    $( function() {
        init_variation_swatches();
    } );
} )( jQuery, document )
