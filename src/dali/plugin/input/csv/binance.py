# Copyright 2022 mbianco
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# CSV Format: User_Id,Time,Category,Operation,Order_Id,Transaction_Id,Primary_Asset,Realized_Amount_For_Primary_Asset,Realized_Amount_For_Primary_Asset_In_USD_Value,Base_Asset,Realized_Amount_For_Base_Asset,Realized_Amount_For_Base_Asset_In_USD_Value,Quote_Asset,Realized_Amount_For_Quote_Asset,Realized_Amount_For_Quote_Asset_In_USD_Value,Fee_Asset,Realized_Amount_For_Fee_Asset,Realized_Amount_For_Fee_Asset_In_USD_Value,Payment_Method,Withdrawal_Method,Additional_Note

import logging
import re
from csv import reader
from typing import Dict, List, Optional

from rp2.logger import create_logger
from rp2.rp2_decimal import RP2Decimal
from dali import transaction_resolver

from dali.abstract_input_plugin import AbstractInputPlugin
from dali.abstract_transaction import AbstractTransaction
from dali.configuration import Keyword
from dali.in_transaction import InTransaction
from dali.intra_transaction import IntraTransaction
from dali.out_transaction import OutTransaction

# transaction types
_CRYPTO_DEPOSIT = "Crypto Deposit"
_SELL = "Sell"
_BUY = "Buy"
_CRYPTO_WITHDRAWAL = "Crypto Withdrawal"
_USD_DEPOSIT = "USD Deposit"
_REFERRAL_COMMISSION = "Referral Commission"
_STAKING_REWARDS = "Staking Rewards"
_OTHERS = "Others"


class InputPlugin(AbstractInputPlugin):

    __BINANCE: str = "Binance.us"

    __TIMESTAMP_INDEX = 1
    __TRANSACTION_CATEGORY_INDEX = 2
    __TRANSACTION_TYPE_INDEX = 3
    __TRANSACTION_ID_INDEX = 5
    __CURRENCY_INDEX = 6
    __BASE_ASSET_INDEX = 9
    __BASE_ASSET_AMOUNT_INDEX = 10
    __BASE_ASSET_AMOUNT_SPOT_PRICE_INDEX = 11

    # amounts in binance tax CSVs are not comma separated and are nicely formatting floating point values
    __PRIMARY_ASSET_AMOUNT = 7
    __PRIMARY_ASSET_SPOT_PRICE = 8

    __DELIMITER = ","

    def __init__(
        self,
        account_holder: str,
        transaction_csv_file: str,
        native_fiat: Optional[str] = None,
    ) -> None:

        super().__init__(account_holder=account_holder, native_fiat=native_fiat)
        self.__transaction_csv_file: str = transaction_csv_file
        self.__logger: logging.Logger = create_logger(f"{self.__BINANCE}/{self.account_holder}")

    def load(self) -> List[AbstractTransaction]:
        result: List[AbstractTransaction] = []

        with open(self.__transaction_csv_file, encoding="utf-8") as transaction_csv_file:
            # read CSV with header and skip first row
            lines = reader(transaction_csv_file)

            # Skip header line
            header = next(lines)
            self.__logger.debug("Header: %s", header)

            for line in lines:
                raw_data: str = self.__DELIMITER.join(line)
                self.__logger.debug("Transaction: %s", raw_data)

                transaction_id: str = line[self.__TRANSACTION_ID_INDEX].strip()
                transaction_type: str = line[self.__TRANSACTION_TYPE_INDEX].strip()
                category = line[self.__TRANSACTION_CATEGORY_INDEX].strip()
                currency: str = line[self.__CURRENCY_INDEX].strip()

                # there is no timezone information in the CSV, so we assume UTC
                timestamp_with_timezone = f"{line[self.__TIMESTAMP_INDEX].strip()} -00:00"

                common_params = {
                    "plugin": self.__BINANCE,
                    "unique_id": transaction_id,
                    "raw_data": raw_data,
                    "timestamp": timestamp_with_timezone,
                    "notes": f"{category} - {transaction_type}",
                }

                # in binance, you can pay fees with lots of different currencies. Since dali does not allow us to specify a fee currency, we use the normalized USD fee amount
                # this impacts buy & sell transactions

                # staking rewards & commission do not have any fees and only have a primary asset
                if transaction_type in [_REFERRAL_COMMISSION, _STAKING_REWARDS]:
                    granular_transaction_type = Keyword.INCOME if transaction_type == _REFERRAL_COMMISSION else Keyword.INTEREST
                    currency: str = line[self.__CURRENCY_INDEX].strip()

                    result.append(
                        InTransaction(
                            **(
                                common_params
                                | {
                                    "asset": currency,
                                    "exchange": self.__BINANCE,
                                    "holder": self.account_holder,
                                    "transaction_type": granular_transaction_type.value,
                                    "spot_price": line[self.__PRIMARY_ASSET_SPOT_PRICE].strip(),
                                    "crypto_in": line[self.__PRIMARY_ASSET_AMOUNT].strip(),
                                    "fiat_fee": "0",
                                }
                            )
                        )
                    )
                elif transaction_type == _CRYPTO_DEPOSIT:
                    currency: str = line[self.__CURRENCY_INDEX].strip()

                    result.append(
                        IntraTransaction(
                            **(
                                common_params
                                | {
                                    "asset": currency,
                                    "crypto_sent": "0",
                                    "crypto_received": line[self.__PRIMARY_ASSET_AMOUNT].strip(),
                                    "spot_price": line[self.__PRIMARY_ASSET_SPOT_PRICE].strip(),
                                    # most likely, funds are coming from the user/tax payer, but we can't say for sure so we use unknown
                                    # and let the user manually input the owner of these funds.
                                    "from_exchange": Keyword.UNKNOWN.value,
                                    "from_holder": Keyword.UNKNOWN.value,
                                    "to_exchange": self.__BINANCE,
                                    "to_holder": self.account_holder,
                                }
                            )
                        )
                    )
                elif transaction_type == _CRYPTO_WITHDRAWAL:
                    # TODO withdrawals can have fees in binance, but it doesn't look like IntraTransaction supports recording fees, not sure what to do here
                    result.append(
                        IntraTransaction(
                            **(
                                common_params
                                | {
                                    "crypto_received": "0",
                                    # withdrawals seem to happen in the primary asset field
                                    "asset": currency,
                                    "crypto_sent": line[self.__PRIMARY_ASSET_AMOUNT].strip(),
                                    "spot_price": line[self.__PRIMARY_ASSET_SPOT_PRICE].strip(),
                                    "from_exchange": self.__BINANCE,
                                    "from_holder": self.account_holder,
                                    # most likely, funds are coming from the user/tax payer, but we can't say for sure so we use unknown
                                    # and let the user manually input the owner of these funds.
                                    "to_exchange": Keyword.UNKNOWN.value,
                                    "to_holder": Keyword.UNKNOWN.value,
                                }
                            )
                        )
                    )
                elif transaction_type in [_BUY, _SELL]:
                    result.append(
                        InTransaction(
                            **(
                                common_params
                                | {
                                    "exchange": self.__BINANCE,
                                    "holder": self.account_holder,
                                    "transaction_type": Keyword.BUY.value,
                                    "asset": line[self.__BASE_ASSET_INDEX].strip(),
                                    "crypto_in": line[self.__BASE_ASSET_AMOUNT_INDEX].strip(),
                                    "spot_price": line[self.__BASE_ASSET_AMOUNT_SPOT_PRICE_INDEX].strip(),
                                    # TODO it's unclear if `crypto_fee` is the USD amount of the crypto-paid fee
                                    # we'll use the USD value for now and see what comes up in PR review
                                    "crypto_fee": line[self.__BASE_ASSET_AMOUNT_SPOT_PRICE_INDEX].strip(),
                                }
                            )
                        )
                    )
                elif transaction_type == _SELL:
                    result.append(
                        OutTransaction(
                            **(
                                common_params
                                | {
                                    "exchange": self.__BINANCE,
                                    "holder": self.account_holder,
                                    "transaction_type": Keyword.SELL.value,
                                    "assets": line[self.__BASE_ASSET_INDEX].strip(),
                                    "crypto_out_no_fee": line[self.__BASE_ASSET_AMOUNT_INDEX].strip(),
                                    "spot_price": line[self.__BASE_ASSET_AMOUNT_SPOT_PRICE_INDEX].strip(),
                                    # TODO it's unclear if `crypto_fee` is the USD amount of the crypto-paid fee
                                    # we'll use the USD value for now and see what comes up in PR review
                                    "crypto_fee": line[self.__BASE_ASSET_AMOUNT_SPOT_PRICE_INDEX].strip(),
                                }
                            )
                        )
                    )
                elif transaction_type == _USD_DEPOSIT:
                    # we only care when USD is used to buy something, so we can skip the deposit entries
                    self.__logger.debug("Skipping USD deposit %s", raw_data)
                else:
                    # TODO I've seen some "Distrubition > Others" but there is no indication about what they respresent
                    # TODO in my data, I had no withdrawals, they will need to be implemented in the future
                    self.__logger.error("Unsupported transaction type (skipping): %s. Please open an issue at %s", raw_data, self.ISSUES_URL)

        return result
