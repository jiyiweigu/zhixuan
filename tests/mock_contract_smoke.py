text=open('frontend/src/mocks/index.ts',encoding='utf-8').read()
assert all(x in text for x in ['source_name','source_url','year'])
assert 'confidence:.42' in text and 'citations:[]' in text
print('mock contract smoke check passed')
