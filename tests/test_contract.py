"""Contract regressions: validate OpenAPI and actual wire examples, not server behavior."""
from pathlib import Path
import unittest

import yaml
from openapi_schema_validator import OAS30Validator
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / 'openapi.yaml').read_text())


def resolve(value):
    """Expand local references; this contract has no recursive schemas."""
    if isinstance(value, dict):
        if '$ref' in value:
            target = SPEC
            for part in value['$ref'][2:].split('/'):
                target = target[part]
            return resolve(target)
        return {key: resolve(child) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve(child) for child in value]
    return value


def validator(name):
    return OAS30Validator(resolve(SPEC['components']['schemas'][name]),
                          format_checker=OAS30Validator.FORMAT_CHECKER)


class ContractTests(unittest.TestCase):
    instruction = dict(instructionId=1, investmentId=2,
                       instructionType='INVEST', amount=100, investmentPlanId=3)

    def test_openapi_structure(self):
        validate(SPEC)

    def test_every_embedded_media_example(self):
        checked = 0
        def visit(node, path='root'):
            nonlocal checked
            if isinstance(node, dict):
                if 'schema' in node and 'example' in node:
                    with self.subTest(path=path):
                        OAS30Validator(resolve(node['schema']),
                            format_checker=OAS30Validator.FORMAT_CHECKER).validate(node['example'])
                    checked += 1
                for key, value in node.items():
                    visit(value, f'{path}/{key}')
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    visit(value, f'{path}/{index}')
        visit(SPEC)
        self.assertGreaterEqual(checked, 10)

    def test_instruction_types_and_required_amount(self):
        check = validator('InstructionRequest')
        for kind in ('INVEST', 'DIVEST'):
            item = dict(self.instruction, instructionType=kind)
            check.validate(item)
            for amount in (None, 0, -1, '100', 2**63):
                with self.subTest(kind=kind, amount=amount):
                    self.assertFalse(check.is_valid(dict(item, amount=amount)))
            del item['amount']
            self.assertFalse(check.is_valid(item))
        for kind in ('BUY', 'SELL', 'UNKNOWN'):
            self.assertFalse(check.is_valid(dict(self.instruction, instructionType=kind)))

    def test_batch_envelope_and_optional_totals(self):
        check = validator('InstructionBatchRequest')
        batch = dict(instructionBatchId=10, instructions=[self.instruction])
        check.validate(batch)
        check.validate(dict(batch, sumInvest=100, sumDivest=0))
        for change in ({'instructions': []}, {'instructionBatchId': 0},
                       {'sumInvest': None}, {'sumDivest': -1}, {'extra': 1}):
            self.assertFalse(check.is_valid(dict(batch, **change)))
        self.assertFalse(check.is_valid([self.instruction]))

    def test_submission_result_invariants(self):
        check = validator('InstructionBatchResult')
        error = dict(code='INVALID_REQUEST', message='Invalid item')
        check.validate(dict(instructionId=1, status='PENDING'))
        check.validate(dict(instructionId=None, status='REJECTED', error=error))
        check.validate(dict(instructionId=1, status='REJECTED', error=error))
        for item in (dict(instructionId=None, status='PENDING'),
                     dict(instructionId=1, status='PENDING', error=error),
                     dict(instructionId=1, status='REJECTED'),
                     dict(instructionId=1, status='COMPLETED')):
            self.assertFalse(check.is_valid(item))

    def test_partial_completion_only_at_batch_level(self):
        self.assertFalse(validator('InstructionStatus').is_valid('PARTIALLY_COMPLETED'))
        validator('InstructionBatchDetailsResponse').validate(
            dict(instructionBatchId=1, status='PARTIALLY_COMPLETED'))
        self.assertFalse(validator('InstructionDetailsResponse').is_valid(
            dict(self.instruction, status='PARTIALLY_COMPLETED')))

    def test_signed_cash_and_net_valuation(self):
        account = dict(investmentId=2, investmentPlanId=3, cashBalance=-2000000,
                       investmentValue=7000000, assets=[dict(isin='IRTKMOFD0001',
                       symbol='عیار', quantity=900, lastMarketPrice=10000)],
                       timestamp='2026-10-07T08:00:00Z')
        check = validator('InvestmentDetailsResponse')
        check.validate(account)
        self.assertEqual(account['investmentValue'], account['cashBalance'] + sum(
            a['quantity'] * a['lastMarketPrice'] for a in account['assets']))
        check.validate(dict(account, investmentValue=-1000000))
        self.assertFalse(check.is_valid(dict(account, cashBalance=-(2**63)-1)))

    def test_buy_sell_require_trade_and_cash_movements_forbid_it(self):
        check = validator('InvestmentTransaction')
        base = dict(transactionId=1, amount=100, timestamp='2026-10-07T08:00:00Z')
        trade = dict(isin='IRTKMOFD0001', symbol='عیار', symbolName='صندوق عیار',
                     quantity=10, price=10)
        for kind in ('BUY', 'SELL'):
            check.validate(dict(base, type=kind, trade=trade))
            self.assertFalse(check.is_valid(dict(base, type=kind)))
        for kind in ('DEPOSIT', 'WITHDRAW'):
            check.validate(dict(base, type=kind))
            self.assertFalse(check.is_valid(dict(base, type=kind, trade=trade)))

    def test_examples_have_consistent_valuation_and_totals(self):
        account = SPEC['paths']['/investments/{investmentId}']['get']['responses']['200']['content']['application/json']['example']
        self.assertEqual(account['investmentValue'], account['cashBalance'] + sum(
            a['quantity'] * a['lastMarketPrice'] for a in account['assets']))
        batch = SPEC['paths']['/instructions/batch']['post']['requestBody']['content']['application/json']['example']
        for kind, total in [('INVEST', 'sumInvest'), ('DIVEST', 'sumDivest')]:
            self.assertEqual(batch[total], sum(i['amount'] for i in batch['instructions']
                                              if i['instructionType'] == kind))

    def test_utc_timestamp_wire_format(self):
        check = validator('InvestmentTransaction')
        base = dict(transactionId=1, type='DEPOSIT', amount=100)
        check.validate(dict(base, timestamp='2026-10-07T08:00:00.123Z'))
        for timestamp in ('2026-10-07T11:30:00+03:30', '2026-10-07T08:00:00',
                          '2026-99-07T08:00:00Z'):
            self.assertFalse(check.is_valid(dict(base, timestamp=timestamp)))

    def test_all_get_operations_document_invalid_parameters(self):
        for path, operations in SPEC['paths'].items():
            if 'get' in operations:
                with self.subTest(path=path):
                    response = resolve(operations['get']['responses']['400'])
                    self.assertEqual(response['content']['application/json']['example']['code'],
                                     'INVALID_REQUEST')

    def test_journey_names_existing_endpoints(self):
        import re
        journey = (ROOT / 'investment-journey.md').read_text()
        for method, path in re.findall(r'`(GET|POST) (/[^`]+)`', journey):
            with self.subTest(method=method, path=path):
                self.assertIn(method.lower(), SPEC['paths'][path])
        self.assertNotIn('ثبت `DIVEST` / `INVEST` در حساب', journey)


if __name__ == '__main__':
    unittest.main()
