from setuptools import setup

def readme():
    with open('README.rst') as f:
        return f.read()

setup(name='allow2',
      version='0.3',
      description='OpenSource Parental Freedom Platform',
      long_description=readme(),
      classifiers=[
        'Development Status :: 3 - Alpha',
        'Programming Language :: Python :: 2.7',
        'Topic :: Text Processing :: Linguistic',
      ],
      keywords=['parental','controls','time','limit'],
      url='http://github.com/Allow2/Allow2python',
      author='Allow2',
      author_email='ceo@allow2.com',
      packages=['allow2'],
      install_requires=[
          'human_curl',
      ],
      include_package_data=True,
      zip_safe=False,
      download_url = 'https://github.com/Allow2/Allow2Python/archive/0.3.tar.gz'
)
