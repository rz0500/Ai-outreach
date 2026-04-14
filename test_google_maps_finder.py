import unittest
from unittest.mock import patch, MagicMock
import google_maps_finder

class TestGoogleMapsFinder(unittest.TestCase):

    @patch('google_maps_finder.get_googlemaps_client')
    @patch('google_maps_finder.database.search_by_company')
    @patch('google_maps_finder.database.add_prospect')
    def test_search_local_businesses(self, mock_add, mock_search, mock_client_getter):
        mock_client = MagicMock()
        mock_client_getter.return_value = mock_client
        
        # Mock places() response
        mock_client.places.return_value = {
            'results': [
                {'place_id': '123', 'name': 'Acme Plumbing'},
                {'place_id': '456', 'name': 'Bob Plumbing'}
            ]
        }
        
        # Mock place() details
        def side_effect_place(place_id, *args, **kwargs):
            if place_id == '123':
                return {'result': {'name': 'Acme Plumbing', 'formatted_phone_number': '555-1234', 'website': 'acme.com'}}
            else:
                return {'result': {'name': 'Bob Plumbing', 'formatted_phone_number': '555-9999'}}
        
        mock_client.place.side_effect = side_effect_place
        
        # Mock db search to say Bob Plumbing already exists, but Acme does not
        def side_effect_search(company_name, *args, **kwargs):
            if company_name == 'Bob Plumbing':
                return [{'id': 2, 'company': 'Bob Plumbing'}]
            return []
            
        mock_search.side_effect = side_effect_search
        
        added = google_maps_finder.search_local_businesses("plumbers", "Austin, TX")
        
        # Assertions
        self.assertEqual(added, 1, "Only Acme Plumbing should be added since Bob is a duplicate")
        mock_add.assert_called_once()
        args, kwargs = mock_add.call_args
        self.assertEqual(kwargs['company'], 'Acme Plumbing')
        self.assertEqual(kwargs['phone'], '555-1234')

if __name__ == '__main__':
    unittest.main()
