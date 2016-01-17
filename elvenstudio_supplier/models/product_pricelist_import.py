# -*- encoding: utf-8 -*-

from openerp import models, fields, exceptions, api, _
import openerp.addons.decimal_precision as dp

import logging

_logger = logging.getLogger(__name__)


class ProductPricelistImport(models.Model):
    _name = 'product.pricelist.import'
    _description = 'Product Price List Import'

    name = fields.Char('Load')
    date = fields.Datetime('Date:', readonly=True)
    process_start_date = fields.Datetime('Date:', readonly=True)
    process_end_date = fields.Datetime('Date:', readonly=True)
    file_name = fields.Char('File Name', readonly=True)
    fails = fields.Integer('Fail Lines:', readonly=True)
    process = fields.Integer('Lines to Process:', readonly=True)
    supplier = fields.Many2one('res.partner', required=True)

    file_lines = fields.One2many(
        comodel_name='product.pricelist.import.line',
        inverse_name='file_import',
        string='Product Price List Lines')

    @api.multi
    def process_lines(self):

        for file_load in self:
            start_date = fields.Datetime.now()
            fail_lines = file_load.fails

            if not file_load.supplier:
                raise exceptions.Warning(_("You must select a Supplier"))

            if not file_load.file_lines:
                raise exceptions.Warning(_("There must be one line at least to process"))

            product_obj = self.env['product.product']
            product_supplier_info_obj = self.env['product.supplierinfo']
            price_list_partner_info_obj = self.env['pricelist.partnerinfo']

            product_to_sort = set()
            product_to_check_mto = set()
            multi_supplier_lines = []
            multi_product_lines = []
            no_product_lines = []
            no_product_code_lines = []

            for line in file_load.file_lines:
                # process fail lines
                if line.fail:

                    # search product code
                    if line.code:
                        product_list = product_obj.search([('default_code', '=', line.code)])

                        if len(product_list) == 1:

                            product_tmpl = product_list[0].product_tmpl_id

                            # Cerco il vecchio riferimento al fornitore
                            supplier = product_supplier_info_obj.search([('product_tmpl_id', '=', product_tmpl.id),
                                                                         ('name', '=', file_load.supplier.id)])
                            # Se esiste lo aggiorno
                            if len(supplier) == 1:
                                # TODO trasferire i dati in una model di storicizzazione?
                                supplier.write({
                                    'name': file_load.supplier.id,
                                    'product_tmpl_id': product_tmpl.id,
                                    'product_name': line.supplier_name,
                                    'product_code': line.supplier_code,
                                    'available_qty': line.available_qty,
                                    'delay': line.delay,
                                    'last_modified_date': fields.Datetime.now(),
                                    'supplier_pricelist_import_id': file_load.id,
                                    'sort_suppliers': False,
                                })

                                if supplier.pricelist_ids.ids:
                                    # TODO gestire le fasce
                                    supplier.pricelist_ids[0].write({
                                        'min_quantity': product_supplier_info_obj.min_qty,
                                        'price': line.price,
                                        'discount': line.discount,
                                        'sort_suppliers': False,
                                    })

                                else:
                                    # TODO gestire le fasce
                                    price_list_partner_info_obj.create({
                                        'suppinfo_id': supplier.id,
                                        'min_quantity': product_supplier_info_obj.min_qty,
                                        'price': line.price,
                                        'discount': line.discount,
                                        'sort_suppliers': False,
                                    })

                                # file_load.fails -= 1  -- avoid write
                                fail_lines -= 1
                                line.write({
                                    'product_id': product_tmpl.id,
                                    'fail': False,
                                    'fail_reason': _('Correctly Updated')
                                })

                                # Se effettuo una modifica, sul prodotto devo verificare l'ordine dei fornitori
                                # Ma non devo attivare l'MTO in quanto già attivo (ha almeno un fornitore)
                                product_to_sort.add(product_tmpl.id)

                            # Non esiste e lo creo
                            elif len(supplier) == 0:

                                product_supplier_info_obj = product_supplier_info_obj.create({
                                    'name': file_load.supplier.id,
                                    'product_tmpl_id': product_tmpl.id,
                                    'product_name': line.supplier_name,
                                    'product_code': line.supplier_code,
                                    'available_qty': line.available_qty,
                                    'delay': line.delay,
                                    # 'last_modified_date': fields.Datetime.now(),
                                    'supplier_pricelist_import_id': file_load.id,
                                    'sort_suppliers': False,
                                    'update_mto_route': False,
                                })

                                # TODO gestire le fasce
                                price_list_partner_info_obj.create({
                                    'suppinfo_id': product_supplier_info_obj.id,
                                    'min_quantity': product_supplier_info_obj.min_qty,
                                    'price': line.price,
                                    'discount': line.discount,
                                    'sort_suppliers': False,
                                })

                                # file_load.fails -= 1  -- avoid write
                                fail_lines -= 1
                                line.write({
                                    'product_id': product_tmpl.id,
                                    'fail': False,
                                    'fail_reason': _('Correctly Added')
                                })

                                # Se aggiungo un fornitore, devo sicuramente verificare che MTO sia attivo
                                # Ma devo anche aggiornare l'ordine dei fornitori, perchè potrebbero
                                # essercene altri già presenti
                                product_to_check_mto.add(product_tmpl.id)
                                product_to_sort.add(product_tmpl.id)

                            # Ci sono almeno due righe con lo stesso fornitore,
                            # è un errore da mostrare
                            else:
                                # line.fail_reason = _('Multiple Supplier Line found') -- avoid write
                                multi_supplier_lines.append(line.id)

                        elif len(product_list) > 1:
                            # line.fail_reason = _('Multiple Products found') -- avoid write
                            multi_product_lines.append(line.id)

                        else:
                            # line.fail_reason = _('Product not found') -- avoid write
                            no_product_lines.append(line.id)

                    else:
                        # line.fail_reason = _('No Product Code') -- avoid write
                        no_product_code_lines.append(line.id)

            # Aggiorno le righe che hanno lo stesso fornitore più volte
            if multi_supplier_lines:
                file_load.file_lines.browse(multi_supplier_lines).write({'fail_reason': _('Multiple Supplier Line found')})

            # Aggiorno le righe che hanno più prodotti con lo stesso codice
            if multi_product_lines:
                file_load.file_lines.browse(multi_product_lines).write({'fail_reason': _('Multiple Products found')})

            # Aggiorno le righe che non hanno prodotti
            if no_product_lines:
                file_load.file_lines.browse(no_product_lines).write({'fail_reason': _('Product not found')})

            # Aggiorno le righe che non hanno il codice prodotto
            if no_product_code_lines:
                file_load.file_lines.browse(no_product_lines).write({'fail_reason': _('No Product Code')})

            # Cerco i prodotti che hanno un riferimento a questo fornitore
            # e che non sono stati aggiornati dal file perchè devo rimuoverli
            supplier_to_remove = product_supplier_info_obj.search(
                [
                    ('name', '=', file_load.supplier.id),
                    ('supplier_pricelist_import_id', '!=', file_load.id)
                ]
            )

            # _logger.warning("SUPPLIER TO REMOVE " + str(supplier_to_remove))

            # Rimuovo i supplier vecchi se ce ne sono
            # Ovvero quelli importati con un listino diverso da quello attuale
            if supplier_to_remove.ids:
                supplier_to_remove.unlink()

            # _logger.warning("PRODUCT TO SORT " + str(product_to_sort))
            if product_to_sort:
                self.env['product.template'].browse(list(product_to_sort)).sort_suppliers()

            # _logger.warning("PRODUCT TO CHECK MTO " + str(product_to_check_mto))
            if product_to_check_mto:
                self.env['product.template'].browse(list(product_to_check_mto)).update_mto_route()

            end_date = fields.Datetime.now()
            file_load.write({'fails': fail_lines, 'process_start_date': start_date, 'process_end_date': end_date})

        return True


class ProductPricelistImportLine(models.Model):
    _name = 'product.pricelist.import.line'
    _description = 'Product Price List Import Line'

    code = fields.Char('Product Code')
    supplier_code = fields.Char('Supplier Product Code')
    supplier_name = fields.Char('Supplier Product Name')

    price = fields.Float('Product Price', required=True)
    discount = fields.Float('Product Discount')

    available_qty = fields.Float('Available Quantity',
                                 required=True,
                                 help="The available quantity that can be purchased from this supplier, expressed"
                                 " in the supplier Product Unit of Measure if not empty, in the default"
                                 " unit of measure of the product otherwise.",
                                 digits=dp.get_precision('Product Unit of Measure'))

    delay = fields.Integer('Delivery Lead Time',
                           required=True,
                           help="Lead time in days between the confirmation of the purchase order and the receipt "
                                "of the products in your warehouse. Used by the scheduler for automatic computation "
                                "of the purchase order planning.")

    product_id = fields.Many2one('product.template',
                                 string='Product',
                                 required=False,
                                 help='The Product related during the load process')

    fail = fields.Boolean('Fail')
    fail_reason = fields.Char('Fail Reason')
    file_import = fields.Many2one('product.pricelist.import', 'File Import', required=True)
